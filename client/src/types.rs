use serde::{Deserialize, Serialize};
use std::error::Error;
use std::fmt::{self, Display, Formatter};
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
* Buying -> Subscribing
* Selling -> Subscribing
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

/*
struct ActivePosition {
    symbol: String,
    position: f32,
}

impl ActivePosition {
    fn sell(&mut self, sell_volume: f32) {
        debug_assert!(self.position > 0_f32);
        self.position -= sell_volume;
    }

    fn buy(&mut self, buy_volume: f32) {
        self.position += buy_volume;
    }
}
*/

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

    pub fn handshake(&self) -> ServerMessageResult {
        if !matches!(self.state, ClientState::HandShake) {
            return Err(StateError::new(StateErrorVariant::HandShake));
        }

        self.generate_server_message()
    }

    #[allow(dead_code)]
    pub fn reinstate_handshake(&mut self) -> ServerMessageResult {
        let prev_state = self.state;
        self.state = ClientState::HandShake;
        let message = self.generate_server_message()?;
        self.state = prev_state;
        Ok(message)
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
                let handshake_message = MessageParameters::HandShake {
                    symbol: &self.symbol,
                };
                serde_json::to_string::<MessageParameters>(&handshake_message)
            }
            ClientState::Buying => {
                let buy_order = self.current_stake - self.previous_stake;
                let buy_message = MessageParameters::SubmitBuyOrder { buy_order };

                serde_json::to_string::<MessageParameters>(&buy_message)
            }
            ClientState::Selling => {
                let sell_order = self.previous_stake - self.current_stake;
                let sell_message = MessageParameters::SubmitSellOrder { sell_order };

                serde_json::to_string::<MessageParameters>(&sell_message)
            }
            ClientState::Subscribed => {
                let message = MessageParameters::Subscribe {
                    publish_cadence: self.sub_parameters.cadence,
                    window: self.sub_parameters.window,
                };

                serde_json::to_string::<MessageParameters>(&message)
            }
            ClientState::Closing => {
                let status = String::from("OK");
                let message = MessageParameters::CloseConnection { status: &status };
                serde_json::to_string::<MessageParameters>(&message)
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
pub enum MessageParameters<'de> {
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

#[cfg(test)]
mod test {
    use super::*;

    #[test]
    fn client_message_test() {
        let symbol = String::from("symbol");
        let handshake = MessageParameters::HandShake { symbol: &symbol };
        let handshake_str = serde_json::to_string_pretty::<MessageParameters>(&handshake).unwrap();
        println!("{}", handshake_str);
    }

    #[test]
    fn test_server_subscription_base() {
        let mut server_sub = ServerSubscription::new(String::from("Symbol"));
        let handshake = server_sub.handshake().unwrap();
        println!("handshake:\n{}", handshake);
        let sub_msg = server_sub.update_parameters(10, 60).unwrap();
        println!("subscribe:\n{}", sub_msg);
        let buy_msg = server_sub.submit_buy(10_f32).unwrap();
        println!("buy msg:\n{}", buy_msg);
        let sell_msg = server_sub.submit_sell(5_f32).unwrap();
        println!("sell msg:\n{}", sell_msg);
    }
}
