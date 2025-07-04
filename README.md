# Modified Publish Subscribe Protocol
- This is a modified publish subscribe protocol I am thinking through for an application I am developing
- The application has a three main component
    - an application where transactions are made, and where events are published from
    - a message broker which serves as a proxy
    - a service where the core application logic lives
- the core application logic takes in events at some cadence, and runs some computations to determine whether a decision should be made regarding the entity
- the message broker only serves as a procy between the transaction service
- the core applcation will need events at different cadences and for different windows depending on where an entity is within its lifecylce
- so we need a protocol that allows us to adjust the rate at which messages are publish, and the polling window
- The reason for this protocol is that the application where transactions are made is a trusted black box service
    - Clients are offered in Python and Java
    - The core application logic is written in Rust
    - Thus, there needs to be a lightweight bi-directional message broker to communicate between the services
## Overview
- this is well suited for applications that need to receive a stream of events, and at some point perform some action
- The application in mind is designed to poll an application for some period time
- These polling windows need to be dynamic based on the application state and will change throughout the lifecyle of the application
- the rate at which messages are published also needs to be dynamic based on the application state for a given entity
- pub-sub subscriptions will be renewed at the end of every subscription window
- then the subscriber will subscribe again based on the new messageing needs of the client
- the messsaging protocol will be served over websockets
- the client will connect to the message broker
- the message broker will handle the events from the transaction service, queue them, and publish them to the client
- the message broker may also aggregate the events based on the publishing cadence the client has requested
## Subscription
- client will connect via a websocket to the server
- once the hadnshake is established, client will send up to the server the length of the subscription and at what cadence messages should be published
- this signifies the client has subscribed for some period of time
- the client will then wait for messages to be publihsed at the rate they subscribed to
- at the end of the subscribed window, the client then will then choose what it wants to do next
- this can one of the following
    - subscribe with the same parameters
    - subscribe with new parameters
    - route to a the connection to an another service on the message broker to perform some transaction within the transaction service
    - close the connection as the lifecycle of the entity is complete
- the client will need to listen for the messages and determine whether it is a ping message, if so return a pong message
- when the message is a pub from the broker, the message will be consumed and use in within the application logic
## Publish
- There are two main ways the client can prompt the message broker to perform some action on the server
1. Action is performed at the end of a micro-subscription
2. The client sends a message to interrupt the micro-subscription
    - This effectively cancels the current micro-subscritpion
    - The messabe broker then propogates on the action on the transaction service

## Message Structure
- The Client and MessageBroker need to agree on a contract
- This is a closed loop system for now so this is not a concern

## State Handling
- The client and message broker will have some shared state to decrease the size of the messages passed through the broker
- Each connection will hold some state
- The initial state on the message broker will be established on a handshake message
- State will be update on each transaction on the client and the message broker
- Assertions will be used during development and maybe production
    - Client will request connection state from the message broker and perform assertions to make sure state is consistent


## Protocol
Here we define the three actors as so:
- Client: Where core application logic sits
- Message Broker: The broker between the transaction service and the core application logic
- Transaction Service: Where transactions occur
1. Every Connection will start with a Handshake
    a. Client will connect with some parameters that will be used to connect to the transaction service
    b. Message Broker will attempt to create a connection to the transaction service
    c. Upon success, the message broker will acknowledge the handshake with the Client
    d. Upon failure, the message broker will communicate reason. ie client error, transaction service connection error, etc
2. Following wil be some comination of subscription windows/submit transactions
