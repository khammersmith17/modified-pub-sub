use bytes::Bytes;
use futures::stream::FuturesUnordered;
use futures::{SinkExt, StreamExt};
use std::error::Error;
use tokio_tungstenite::connect_async;
use tungstenite::Message;
mod types;
use rand::random_range;
use std::time::Instant;
use types::{MessageBrokerClient, PubMessage};
mod ack_types;
pub mod money;

#[tokio::main]
async fn main() -> Result<(), Box<dyn Error + Send + Sync + 'static>> {
    let task_futures: FuturesUnordered<_> = (0..3)
        .map(|i| tokio::task::spawn(async move { run_concurrent_process(i).await }))
        .collect();

    task_futures.for_each(|_| async {}).await;
    Ok(())
}

async fn run_concurrent_process(id: u8) -> Result<(), Box<dyn Error + Send + Sync + 'static>> {
    println!("Running sim with: {id}");
    let (stream, _) = connect_async("ws://localhost:8080/base").await?;

    let (mut writr, mut recvr) = stream.split();

    let mut symbol = String::new();

    symbol.push(id as char);

    /*
        let mut server_sub = MessageBrokerClient::new(symbol);

        writr
            .send(Message::Binary(Bytes::from(server_sub.handshake()?)))
            .await?;
        println!("sent handshake for: {id}");
        writr
            .send(Message::Binary(Bytes::from(
                server_sub.update_parameters(1_u16, 5_u16)?,
            )))
            .await?;
        println!("updated parameters for: {id}");

        let mut num_messages = 0_usize;
        while num_messages < 5 {
            let now = Instant::now();
            let Some(data) = recvr.next().await else {
                continue;
            };
            let recv_message = match data {
                Ok(m) => match m {
                    Message::Binary(b) => {
                        let decoded_data = serde_json::from_slice::<PubMessage>(&b)?;
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
            println!(
                "recieved message {:?} for {} in {:?}",
                recv_message,
                id,
                now.elapsed()
            );
        }

        writr
            .send(Message::Binary(Bytes::from(
                server_sub.update_parameters(5_u16, 30_u16)?,
            )))
            .await?;

        recvr.next().await;
        recvr.next().await;

        let buy_price: f32 = random_range(4_f32..50_f32);

        println!("buy price: {}", buy_price);

        writr
            .send(Message::Binary(Bytes::from(
                server_sub.submit_buy(buy_price)?,
            )))
            .await?;

        writr
            .send(Message::Binary(Bytes::from(
                server_sub.submit_sell(2.1_f32)?,
            )))
            .await?;

        match server_sub.assert_server_state(&mut writr, &mut recvr).await {
            Ok(_) => println!("assertion successful for {}", id),
            Err(_) => println!("Error in assertion"),
        };

        let _close_message = server_sub.close_connection();
        writr.close().await?;
    */
    Ok(())
}
