use bytes::Bytes;
use futures::stream::{SplitSink, SplitStream};
use futures::{SinkExt, StreamExt};
use serde::{Deserialize, Serialize};
use std::error::Error;
use std::fmt::{self, Display, Formatter};
use std::ops::Index;
use tokio_tungstenite::WebSocketStream;
use tungstenite::Message;
/*
* 5 possible states:
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

type ServerMessageResult = Result<String, StateError>;

#[derive(Debug)]
enum StateErrorVariant {
    HandShake,
    InvalidMessage,
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

pub struct ServerSubscription {
    symbol: String,
    current_stake: f32,
    previous_stake: f32,
    sub_parameters: SubParameters,
    state: ClientState,
}

impl ServerSubscription {
    pub fn new(symbol: String) -> ServerSubscription {
        ServerSubscription {
            symbol,
            current_stake: 0_f32,
            previous_stake: 0_f32,
            sub_parameters: SubParameters::default(),
            state: ClientState::HandShake,
        }
    }

    pub fn update_parameters(&mut self, cadence: u16, window: u16) -> ServerMessageResult {
        self.sub_parameters = SubParameters { cadence, window };
        self.state = ClientState::Subscribed;
        self.generate_server_message()
    }

    pub async fn handshake<T>(
        &self,
        writr: &mut SplitSink<WebSocketStream<T>, Message>,
        recvr: &mut SplitStream<WebSocketStream<T>>,
    ) -> Result<(), Box<dyn Error>>
    where
        T: tokio::io::AsyncRead + tokio::io::AsyncWrite + Unpin,
    {
        // generate the handshake message
        // if there is an error on the message broker, try again
        let base_m = ServerMessage::HandShake {
            symbol: &self.symbol,
        };

        let msg = serde_json::to_string::<ServerMessage>(&base_m)?;

        writr.send(Message::Binary(Bytes::from(msg))).await?;

        while let Some(ack) = recvr.next().await {
            match ack {
                Ok(s_ack) => match s_ack {
                    Message::Binary(m) => {
                        let ack_m = serde_json::from_slice::<HandshakeAck>(&m)?;
                        if matches!(ack_m.status, HandshakeStatus::Success) {
                            return Ok(());
                        } else {
                            return Err("Handshake not successful".into());
                        }
                    }
                    Message::Text(m) => {
                        let ack_m = serde_json::from_str::<HandshakeAck>(&m)?;
                        if matches!(ack_m.status, HandshakeStatus::Success) {
                            return Ok(());
                        } else {
                            return Err("Handshake not successful".into());
                        }
                    }
                    Message::Ping(m) => {
                        // pong back with
                        writr.send(Message::Pong(m)).await?;
                    }
                    Message::Pong(_) => {
                        // can safely accept a pong and let this be an acknowledgement of a live
                        // connection
                        continue;
                    }
                    Message::Close(m) => {
                        writr.send(Message::Close(m)).await?;
                        return Err("Connection closed before handshake recieved".into());
                    }
                    _ => return Err("recieved incomplete message".into()),
                },
                Err(e) => return Err(format!("Handshake not successful: {:?}", e).into()),
            }
        }
        todo!()
    }

    #[allow(dead_code)]
    pub fn reinstate_handshake(&mut self) -> ServerMessageResult {
        let prev_state = self.state;
        self.state = ClientState::HandShake;
        let message = self.generate_server_message()?;
        self.state = prev_state;
        Ok(message)
    }

    pub async fn assert_server_state<T>(
        &self,
        writr: &mut SplitSink<WebSocketStream<T>, Message>,
        recvr: &mut SplitStream<WebSocketStream<T>>,
    ) -> Result<(), Box<dyn Error>>
    where
        T: tokio::io::AsyncRead + tokio::io::AsyncWrite + Unpin,
    {
        let message = serde_json::to_string::<ServerMessage>(&ServerMessage::ServerState {
            symbol: &self.symbol,
        })?;

        writr
            .send(tungstenite::Message::Binary(bytes::Bytes::from(message)))
            .await?;

        let mut recv_message_opt: Option<ServerStateAssertion> = None;

        while recv_message_opt.is_none() {
            let Some(message) = recvr.next().await else {
                return Err("No message".into());
            };

            match message {
                Ok(m) => match m {
                    Message::Text(t) => {
                        let message = serde_json::from_str::<ServerStateAssertion>(&t)?;
                        recv_message_opt = Some(message);
                    }
                    Message::Binary(b) => {
                        let message = serde_json::from_slice::<ServerStateAssertion>(&b)?;
                        recv_message_opt = Some(message);
                    }
                    Message::Close(_) => return Err("Connection Closed".into()),
                    _ => continue,
                },
                Err(_) => {
                    todo!()
                }
            };
        }
        let server_state = recv_message_opt.unwrap();
        println!("current server state: {:?}", server_state);
        println!("current client state: {}", self.current_stake);
        assert!(server_state.stake - self.current_stake < f32::EPSILON);
        Ok(())
    }

    pub fn submit_buy(&mut self, order_amount: f32) -> ServerMessageResult {
        let new_position_value = self.current_stake + order_amount;
        self.previous_stake = self.current_stake;
        self.current_stake = new_position_value;
        self.state = ClientState::Buying;
        self.generate_server_message()
    }

    pub fn submit_sell(&mut self, order_amount: f32) -> ServerMessageResult {
        let new_position_value = self.current_stake - order_amount;
        debug_assert!(new_position_value > 0_f32);

        self.previous_stake = self.current_stake;
        self.current_stake = new_position_value;
        self.state = ClientState::Selling;
        self.generate_server_message()
    }

    pub fn close_connection(&mut self) -> ServerMessageResult {
        self.state = ClientState::Closing;
        let message = self.generate_server_message()?;
        self.state = ClientState::Closed;
        Ok(message)
    }

    fn generate_server_message(&self) -> ServerMessageResult {
        let message: Result<String, serde_json::Error> = match self.state {
            ClientState::HandShake => {
                let handshake_message = ServerMessage::HandShake {
                    symbol: &self.symbol,
                };
                serde_json::to_string::<ServerMessage>(&handshake_message)
            }
            ClientState::Buying => {
                let buy_order = self.current_stake - self.previous_stake;
                let buy_message = ServerMessage::SubmitBuyOrder { buy_order };

                serde_json::to_string::<ServerMessage>(&buy_message)
            }
            ClientState::Selling => {
                let sell_order = self.previous_stake - self.current_stake;
                let sell_message = ServerMessage::SubmitSellOrder { sell_order };

                serde_json::to_string::<ServerMessage>(&sell_message)
            }
            ClientState::Subscribed => {
                let message = ServerMessage::Subscribe {
                    publish_cadence: self.sub_parameters.cadence,
                    window: self.sub_parameters.window,
                };

                serde_json::to_string::<ServerMessage>(&message)
            }
            ClientState::Closing => {
                let status = String::from("OK");
                let message = ServerMessage::CloseConnection { status: &status };
                serde_json::to_string::<ServerMessage>(&message)
            }
            ClientState::Closed => {
                return Err(StateError::new(StateErrorVariant::ConnectionClosed));
            }
        };
        let Ok(payload) = message else {
            return Err(StateError::new(StateErrorVariant::InvalidMessage));
        };
        Ok(payload)
    }

    #[allow(dead_code)]
    pub fn current_state(&self) -> &ClientState {
        &self.state
    }

    pub fn current_position(&self) -> f32 {
        self.current_stake
    }
}

#[derive(Serialize, Deserialize, Debug, Clone, Copy)]
#[serde(rename = "camelCase")]
pub enum ClientState {
    HandShake,
    Buying,
    Selling,
    Subscribed,
    Closing,
    Closed,
}

#[derive(Serialize, Debug)]
#[serde(rename_all = "camelCase")]
pub enum ServerMessage<'de> {
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
        symbol: &'de str,
    },
    HandShake {
        symbol: &'de str,
    },
    CloseConnection {
        status: &'de str,
    },
}

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
