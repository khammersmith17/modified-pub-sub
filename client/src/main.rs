use bytes::Bytes;
use futures::{SinkExt, StreamExt};
use std::error::Error;
use tokio_tungstenite::connect_async;
use tungstenite::Message;
mod types;
use bincode::config;
use std::time::Instant;
use types::{PubMessage, ServerSubscription};

#[tokio::main]
async fn main() -> Result<(), Box<dyn Error + Send + Sync + 'static>> {
    // first connecting to base
    let (stream, _) = connect_async("ws://localhost:8080/base").await?;

    let (mut writr, mut recvr) = stream.split();

    let bincode_config = config::standard();
    let mut server_sub = ServerSubscription::new(String::from("symbol"));

    writr
        .send(Message::Binary(Bytes::from(server_sub.handshake()?)))
        .await?;
    println!("sent handshake");
    writr
        .send(Message::Binary(Bytes::from(
            server_sub.update_parameters(1_u16, 5_u16)?,
        )))
        .await?;
    println!("updated parameters");

    let mut num_messages = 0_usize;
    while num_messages < 5 {
        let now = Instant::now();
        let Some(data) = recvr.next().await else {
            continue;
        };
        let recv_message = match data {
            Ok(m) => match m {
                Message::Binary(b) => {
                    let (decoded_data, _n) =
                        bincode::serde::decode_from_slice::<PubMessage, _>(&b, bincode_config)?;
                    num_messages += 1;
                    decoded_data
                }
                Message::Text(b) => {
                    num_messages += 1;
                    serde_json::from_str::<PubMessage>(b.as_str())?
                }
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

    writr
        .send(Message::Binary(Bytes::from(
            server_sub.update_parameters(5_u16, 30_u16)?,
        )))
        .await?;

    recvr.next().await;
    recvr.next().await;
    writr
        .send(Message::Binary(Bytes::from(server_sub.submit_buy(15_f32)?)))
        .await?;

    let _close_message = server_sub.close_connection();
    writr.close().await?;

    Ok(())
}
