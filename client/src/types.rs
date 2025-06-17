use serde::{Deserialize, Serialize};

#[derive(Serialize)]
pub struct Subscribe {
    pub publish_cadence: u16,
    pub window: u16,
}

#[derive(Deserialize, Debug)]
pub struct PubMessage {
    i: u16,
}
