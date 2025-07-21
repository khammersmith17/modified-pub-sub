use crate::ack_types;
use bytes::Bytes;
use futures::stream::{SplitSink, SplitStream};
use futures::{SinkExt, StreamExt};
use serde::de::DeserializeOwned;
use serde::{Deserialize, Serialize};
use std::error::Error;
use std::fmt::{self, Display, Formatter, Result as FmtResult};
use std::marker::PhantomData;
use std::ops::Index;
use tokio::net::TcpStream;
use tokio_tungstenite::{MaybeTlsStream, WebSocketStream, connect_async};
use tungstenite::Message;
/*
* 5 possible states:
* PreConnection
* PreHandshake
* IntraSession
* HandShake
* Subscribing
* Buying
* Selling
* Closed
*
* To change from adding volume to selling volume and vice versa
* the state must move through a routed connection
*
*----Valid state changes----
* HandShake -> Buying
* Handshake -> Subscribed
* Buying -> Subscribed
* Selling -> Subscribed
* Subscribing -> Buying
* Subscribing -> Selling
* Selling -> Closed
*
*
*
*
*
*
*
* The subscription should internally hold some details, then issue a server message via the server
* message enum
* */

type WebSocketWriter = SplitSink<WebSocketStream<MaybeTlsStream<TcpStream>>, Message>;
type WebSocketReader = SplitStream<WebSocketStream<MaybeTlsStream<TcpStream>>>;

type ThreadSafeError = Box<dyn std::error::Error + Send + Sync + 'static>;

#[derive(Debug, Deserialize)]
pub enum HandshakeStatus {
    Success,
    Failure,
}

#[derive(Debug, Deserialize)]
#[allow(dead_code)]
pub struct HandshakeAck {
    status: HandshakeStatus,
}

#[derive(Debug, Deserialize)]
#[allow(dead_code)]
struct RecievedTicker {
    ticker: Option<BaseTicker>,
}

#[derive(Debug, Deserialize)]
#[allow(dead_code)]
struct BaseTicker {
    h: f32,
    l: f32,
    c: f32,
    o: f32,
    v: f32,
}

// Generic type to hold cap items in a circular buffer
struct CircularBuffer<T> {
    buf: Vec<T>,
    cap: usize,
    i: usize,
}

impl<'a, T> Index<usize> for CircularBuffer<T> {
    type Output = T;
    fn index(&self, idx: usize) -> &Self::Output {
        let j = (self.i + idx) % self.cap;
        &self.buf[j]
    }
}

#[allow(dead_code)]
impl<T> CircularBuffer<T>
where
    T: Default + Clone,
{
    pub fn new(cap: usize) -> CircularBuffer<T> {
        // allocate a Vec with cap
        let mut buf: Vec<T> = Vec::with_capacity(cap);

        // allocate a default item to every position in the Vec
        buf.resize(cap, T::default());

        CircularBuffer {
            buf,
            cap,
            i: 0_usize,
        }
    }

    pub fn push(&mut self, item: T) {
        // insert at i, increment
        self.buf[self.i] = item;
        self.i = (self.i + 1) % self.cap;
    }

    fn aggregate<R, F>(&self, f: F) -> R
    where
        F: Fn(&[T]) -> R,
    {
        f(&self.buf)
    }
}

#[derive(Debug)]
enum StateErrorVariant {
    HandShake,
    InvalidMessage,
    UnsuccessfulHandshake,
    ConnectionClosed,
    #[allow(dead_code)]
    PositionActive,
    #[allow(dead_code)]
    AddVolumeToSell,
    #[allow(dead_code)]
    SellVolumeToAdd,
}

#[derive(Debug)]
pub struct StateError {
    error: StateErrorVariant,
}

impl StateError {
    fn new(error: StateErrorVariant) -> Self {
        Self { error }
    }
}

impl Display for StateError {
    fn fmt(&self, f: &mut Formatter) -> fmt::Result {
        let err_message = match self.error {
            StateErrorVariant::ConnectionClosed => "Connection has been closed",
            StateErrorVariant::AddVolumeToSell => {
                "The connection must routed to volume in before volume buys can be processed"
            }
            StateErrorVariant::SellVolumeToAdd => {
                "The connection must be routed to volume out before sells can be processed"
            }
            StateErrorVariant::PositionActive => {
                "Connection cannot be closed while position is still active"
            }
            StateErrorVariant::InvalidMessage => "Unable to generate message",
            StateErrorVariant::HandShake => "Hand shake already completed",
            StateErrorVariant::UnsuccessfulHandshake => "Hand shake recovery failed",
        };
        write!(f, "{}", err_message)
    }
}

impl Error for StateError {}

#[derive(Default)]
struct SubParameters {
    cadence: u16,
    window: u16,
}

trait PositionState {}

struct PreConnection;

impl PositionState for PreConnection {}

struct PreHandshake;

impl PositionState for PreHandshake {}

struct IntraSession;

impl PositionState for IntraSession {}

struct PostSession;

impl PositionState for PostSession {}

pub struct MessageBrokerClient<S>
where
    S: PositionState,
{
    symbol: String,
    pub_cadence: usize,
    state: PhantomData<S>,
    writr: WebSocketWriter,
    readr: WebSocketReader,
}

impl MessageBrokerClient<PreConnection> {
    pub async fn new(
        symbol: String,
        url: String,
        port: usize,
        endpoint: Option<String>,
    ) -> Result<MessageBrokerClient<PreHandshake>, ThreadSafeError> {
        let mut connection_string = format!("{url}:{port}");
        if let Some(e) = endpoint {
            connection_string.push('/');
            connection_string.push_str(&e);
        }
        let (stream, _) = connect_async(&connection_string).await?;

        let (writr, readr) = stream.split();
        Ok(MessageBrokerClient::<PreHandshake> {
            symbol,
            pub_cadence: 5_usize,
            writr,
            readr,
            state: PhantomData::<PreHandshake>,
        })
    }
}

enum HandshakeError {
    ConnectionError,
    BadHandshake,
}

impl MessageBrokerClient<PreHandshake> {
    pub async fn handshake(
        mut self,
        pt: PositionType,
    ) -> Result<MessageBrokerClient<IntraSession>, Self> {
        // on success move -> IntraSession state
        // on failure, hand back self
        let sm = ServerMessage::SessionHandshake {
            symbol: self.symbol.clone(),
            publish_cadence: 5_u16,
            position_type: pt,
        };
        let Ok(_) = self.send_handshake(sm).await else {
            return Err(self);
        };
        let Ok(_) = self.read_handshake_ack().await else {
            return Err(self);
        };
        let Self {
            symbol,
            pub_cadence,
            readr,
            writr,
            ..
        } = self;
        Ok(MessageBrokerClient::<IntraSession> {
            symbol,
            pub_cadence,
            readr,
            writr,
            state: PhantomData::<IntraSession>,
        })
    }

    async fn send_handshake(&mut self, handshake: ServerMessage) -> Result<(), HandshakeError> {
        let Ok(msg) = serde_json::to_string::<ServerMessage>(&handshake) else {
            return Err(HandshakeError::BadHandshake);
        };
        match self.writr.send(Message::Binary(Bytes::from(msg))).await {
            Ok(_) => Ok(()),
            Err(_) => Err(HandshakeError::ConnectionError),
        }
    }

    async fn read_handshake_ack(&mut self) -> Result<(), HandshakeError> {
        while let Some(ack) = self.readr.next().await {
            match ack {
                Ok(s_ack) => match s_ack {
                    Message::Binary(m) => {
                        if let Ok(ack_m) = serde_json::from_slice::<HandshakeAck>(&m) {
                            if matches!(ack_m.status, HandshakeStatus::Success) {
                                return Ok(());
                            }
                        };
                        return Err(HandshakeError::BadHandshake);
                    }
                    Message::Text(m) => {
                        if let Ok(ack_m) = serde_json::from_str::<HandshakeAck>(&m) {
                            if matches!(ack_m.status, HandshakeStatus::Success) {
                                return Ok(());
                            }
                        };
                        return Err(HandshakeError::BadHandshake);
                    }
                    Message::Ping(m) => {
                        // pong back with
                        let _ = self.writr.send(Message::Pong(m)).await;
                    }
                    Message::Pong(_) => {
                        // can safely accept a pong and let this be an acknowledgement of a live
                        // connection
                        continue;
                    }
                    Message::Close(_) => return Err(HandshakeError::ConnectionError),

                    _ => return Err(HandshakeError::ConnectionError),
                },
                Err(_) => return Err(HandshakeError::ConnectionError),
            }
        }
        Err(HandshakeError::ConnectionError)
    }
}

#[derive(Debug)]
enum SessionError {
    InvalidMessage,
    ConnectionClosed,
    NoAvailableTicker,
    ConnectionReset,
}

impl Display for SessionError {
    fn fmt(&self, f: &mut Formatter) -> FmtResult {
        let msg = match self {
            Self::InvalidMessage => "Message sent to Message Broker invalid",
            Self::ConnectionClosed => "Session Connection is Closed",
            Self::ConnectionReset => "Connection was reset",
            Self::NoAvailableTicker => "No ticker available",
        };

        write!(f, "{msg}")
    }
}

impl std::error::Error for SessionError {}
unsafe impl Send for SessionError {}
unsafe impl Sync for SessionError {}

impl MessageBrokerClient<IntraSession> {
    pub async fn update_parameters(&mut self, cadence: usize) -> Result<(), ThreadSafeError> {
        // send a message to update the parameters
        // need to handle the case where a ticker in the queue, if so handle it
        // wait for an ack
        self.pub_cadence = cadence;
        todo!()
    }

    pub async fn submit_sell_order(
        &mut self,
        order_size: f32,
    ) -> Result<ack_types::OrderAck, SessionError> {
        // try to submit order
        // if order fails with a connection close error, perform recovery handshake
        match self
            .submit_order(order_size, ack_types::OrderType::Sell)
            .await
        {
            Ok(ack) => Ok(ack),
            Err(e) => Err(e),
        }
    }

    async fn submit_order(
        &mut self,
        order_size: f32,
        order_type: ack_types::OrderType,
    ) -> Result<ack_types::OrderAck, SessionError> {
        let order = match order_type {
            ack_types::OrderType::Buy => ServerMessage::SubmitBuyOrder {
                buy_order: order_size,
            },
            ack_types::OrderType::Sell => ServerMessage::SubmitSellOrder {
                sell_order: order_size,
            },
        };
        match self.upsert_message(order).await {
            Ok(_) => {}
            Err(_e) => {
                todo!()
            }
        }
        // read incoming message
        match self.read_message::<ack_types::OrderAck>().await {
            Ok(ack) => Ok(ack),
            Err(e) => Err(e),
        }
    }

    pub async fn submit_buy_order(
        &mut self,
        order_size: f32,
    ) -> Result<ack_types::OrderAck, SessionError> {
        // submit the order
        // if the connection is terminated, recover
        // wait for the ack from the broker
        // give the ack back to the user
        match self
            .submit_order(order_size, ack_types::OrderType::Buy)
            .await
        {
            Ok(ack) => Ok(ack),
            Err(e) => Err(e),
        }
    }

    async fn upsert_message<'a>(&mut self, message: ServerMessage) -> Result<(), ThreadSafeError> {
        let msg = serde_json::to_string::<ServerMessage>(&message)?;
        self.writr.send(Message::Binary(Bytes::from(msg))).await?;
        Ok(())
    }

    pub async fn retrieve_ticker(&mut self) -> Result<Option<BaseTicker>, StateError> {
        match self.read_message::<RecievedTicker>().await {
            Ok(t) => Ok(t.ticker),
            Err(e) => {
                if matches!(e, SessionError::ConnectionClosed) {
                    match self.recovery_handshake().await {
                        Ok(_) => return Ok(None),
                        Err(e) => return Err(e),
                    }
                };
                return Err(StateError {
                    error: StateErrorVariant::InvalidMessage,
                });
            }
        }
    }

    async fn read_message<T>(&mut self) -> Result<T, SessionError>
    where
        T: DeserializeOwned,
    {
        /*
        Idea here is to read a message
        If the message is Ping/Pong respond and wait for the next message
        If we get text or a binary message back we can return it the message enum
        If the connection is closed, return a connection close error
        if we get a frame, the message is invalid, we should probably not get here
        */
        while let Some(msg_res) = self.readr.next().await {
            match msg_res {
                Ok(message) => match message {
                    Message::Binary(data) => {
                        let Ok(data) = serde_json::from_slice::<T>(&data) else {
                            return Err(SessionError::NoAvailableTicker);
                        };
                        return Ok(data);
                    }
                    Message::Text(data) => {
                        let Ok(data) = serde_json::from_str::<T>(&data) else {
                            return Err(SessionError::NoAvailableTicker);
                        };
                        return Ok(data);
                    }
                    Message::Ping(m) => {
                        // pong back
                        let _ = self.writr.send(Message::Pong(m)).await;
                        continue;
                    }
                    Message::Pong(_) => {
                        // ack to a Ping, safely ignore
                        continue;
                    }
                    Message::Close(_) => return Err(SessionError::ConnectionClosed),
                    Message::Frame(_) => return Err(SessionError::InvalidMessage),
                },
                Err(_) => {}
            }
        }
        todo!()
    }

    pub async fn close_connection(self) -> MessageBrokerClient<PostSession> {
        // send close message
        let Self {
            symbol,
            readr,
            writr,
            pub_cadence,
            ..
        } = self;

        return MessageBrokerClient {
            symbol,
            readr,
            writr,
            pub_cadence,
            state: PhantomData::<PostSession>,
        };
    }

    #[allow(dead_code)]
    async fn recovery_handshake(&mut self) -> Result<(), StateError> {
        // start a new connection
        // send a recovery handshake
        // wait for the ack
        let server_message = ServerMessage::RecoveryHandshake {
            symbol: self.symbol.clone(),
        };

        self.upsert_message(server_message);
        match self.read_message::<HandshakeAck>().await {
            Ok(_) => Ok(()),
            Err(_) => Err(StateError {
                error: StateErrorVariant::InvalidMessage,
            }),
        }
    }

    async fn perform_broker_state_assertion(
        &mut self,
    ) -> Result<ack_types::ServerStateAck, SessionError> {
        todo!()
    }
}

#[derive(Debug, Serialize, Deserialize)]
pub enum PositionType {
    Long,
    Short,
}

#[derive(Serialize, Deserialize, Debug, Clone, Copy)]
#[serde(rename = "camelCase")]
pub enum ClientState {
    PreConnection,
    Transaction,
    Subscribed,
    Closed,
}

#[derive(Serialize, Debug)]
#[serde(rename_all = "camelCase")]
pub enum ServerMessage {
    #[serde(rename_all = "camelCase")]
    SubmitBuyOrder {
        buy_order: f32,
    },
    #[serde(rename_all = "camelCase")]
    SubmitSellOrder {
        sell_order: f32,
    },

    #[serde(rename_all = "camelCase")]
    Subscribe {
        publish_cadence: u16,
        window: u16,
    },
    ServerState {
        symbol: String,
    },
    SessionHandshake {
        symbol: String,
        publish_cadence: u16,
        position_type: PositionType,
    },
    RecoveryHandshake {
        symbol: String,
    },
    CloseConnection {
        status: String,
    },
}

/*
*{"Handshake": {
    "symbol": ...
}
* */

#[derive(Deserialize, Debug)]
pub struct PubMessage {
    #[allow(dead_code)]
    i: u16,
}

#[derive(Deserialize, Debug)]
struct ServerStateAssertion {
    symbol: String,
    stake: f32,
}

#[cfg(test)]
mod test {
    use super::*;

    #[test]
    fn circular_buffer() {
        let mut buffer: CircularBuffer<i32> = CircularBuffer::new(5_usize);
        buffer.push(1_i32);
        buffer.push(2_i32);
        buffer.push(3_i32);
        buffer.push(4_i32);
        buffer.push(5_i32);
        buffer.push(6_i32);

        assert_eq!(buffer[0], 2_i32);
    }

    #[test]
    fn circular_buffer_agg() {
        let mut buffer: CircularBuffer<i32> = CircularBuffer::new(5_usize);
        buffer.push(1_i32);
        buffer.push(2_i32);
        buffer.push(3_i32);
        buffer.push(4_i32);
        buffer.push(5_i32);
        buffer.push(6_i32);

        let res: i32 = buffer.aggregate(|data: &[i32]| data.iter().sum());

        assert_eq!(res, 20_i32);
    }
}
