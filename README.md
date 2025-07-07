# Modified Publish Subscribe Protocol
- The following is a modified pub-sub protocol
- It is designed for an application where there is some third party service where transactions might be made, that is decoupled from the main application logic, that may also publish messages
- This may be the case because
    - the transaction service does not offer a client sdk in the preferred language for the application
    - seperation of resposnsibilites
    - fine grained control of messages is desired
- The application has a three main components
    - an application where transactions are made, and where events are published from
    - a message broker which serves as a proxy
    - a service where the core application logic lives
- the core application logic takes in events at some cadence, and runs some computations to determine whether a decision should be made regarding the entity
- the message broker only serves as a proxy between the transaction service
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
- the messsaging protocol will be served over websockets
- the client will connect to the message broker
- the message broker will handle the events from the transaction service, queue them, and publish them to the client
- the message broker may also aggregate the events based on the publishing cadence the client has requested
- The lifecyle of a session is as follows
    1. Following a websocket protocol handshake, client and message broker will perform an appilication level handshake
        - This handshake will ensure that the broker and client share state over the connection
        - This includes an entity identifier, and other application specific parameters
    2. Subscribing to a message stream
        - A subscription message will include subscription parameters
    3. Client interrupts message stream to perform some action
        - This can be an action on the transaction service, or a change to the message stream parameters on the message broker
        - subscription will resume after the broker acknowledges the status of the transaction
    4. steps 2-4 will be performed based on application logic and state
    5. Client can request broker state at any point, to ensure state consistency
    6. If at any point the connection is dropped, the client and send another handshake, indicating a continuation of a current session
    7. Upon the end of the session lifecyle, the client will send a Close frame, and the server will clean up an session related state
- Handshakes, transaction requests, state request will all be acknowledged by the message broker
## State management
- The client and the message broker will have some shared state
    - This state includes entity identifier, subscription parameters, transaction state, etc depending on the application
- Message broker state will be updated during the following phases
    1. Handshake
    2. Client submits a transaction request
    3. Client updates subscription
    4. Client ends session
- Client may request server state to ensure syncronization of state between server and client
