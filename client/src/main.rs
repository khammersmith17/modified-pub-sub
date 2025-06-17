use bytes::Bytes;
use futures::{SinkExt, StreamExt};
use std::error::Error;
use tokio_tungstenite::connect_async;
use tungstenite::Message;
mod types;
use bincode::config;
use std::time::Instant;
use types::{PubMessage, Subscribe};

#[tokio::main]
async fn main() -> Result<(), Box<dyn Error + Send + Sync + 'static>> {
    // first connecting to base
    println!("Connecting to base");
    let (stream, _) = connect_async("ws://localhost:8080/base").await?;

    let (mut writr, mut recvr) = stream.split();

    let subscription_message = Subscribe {
        publish_cadence: 10,
        window: 60,
    };
    let subscription_str = serde_json::to_string(&subscription_message)?;

    let bincode_config = config::standard();

    writr
        .send(Message::Binary(Bytes::from(subscription_str)))
        .await?;
    let mut recieved_messages = 0_usize;
    while recieved_messages < 5 {
        let now = Instant::now();
        let Some(data) = recvr.next().await else {
            continue;
        };
        let recv_message = match data {
            Ok(m) => match m {
                Message::Binary(b) => {
                    let (decoded_data, _n) =
                        bincode::serde::decode_from_slice::<PubMessage, _>(&b, bincode_config)?;
                    recieved_messages += 1;
                    decoded_data
                }
                Message::Text(b) => serde_json::from_str::<PubMessage>(b.as_str())?,
                Message::Ping(_) => {
                    println!("ping");
                    continue;
                }
                Message::Pong(_) => {
                    println!("pong");
                    continue;
                }
                Message::Close(_) => {
                    println!("connected closed");
                    break;
                }
                Message::Frame(f) => {
                    println!("frame:{:?}", f);
                    continue;
                }
            },
            Err(_) => continue,
        };
        println!("recieved message: {:?}", recv_message);
        println!("Elapsed time: {:?}", now.elapsed());
    }

    writr.close().await?;

    println!("Connecting to other");
    let (stream, _) = connect_async("ws://localhost:8080/other").await?;

    let (mut writr, mut recvr) = stream.split();

    writr
        .send(Message::Binary(Bytes::from("Hello from other")))
        .await?;
    for _ in 0..10 {
        tokio::time::sleep(tokio::time::Duration::from_millis(100)).await;
        let Some(data) = recvr.next().await else {
            continue;
        };
        println!("{:?}", data)
    }

    writr.close().await?;

    Ok(())
}
