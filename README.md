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
- the message broker will recieve the subsscription parameters for each micro subscription
- the message broker will determine the number of total messages that will be sent within the window
- for each message to be sent during the micro-subscription
    - a message will be queued from the transaction service
    - any aggregation may be done based on the number of events spawned from the transaction service
    - the message broker will publish a message to the client
- when the subscription window finishes, the message broker will then wait for the next action based on the client response
- if the client requests another micro subscription, then the message broker will repeat this process
- otherwise the message broker will either adjust the subscription parameters, or propogate the connection to the next relevant step

## Message Structure
- there are three broad categories that need to be consider
    1. Subscribing, and subscription renewal
    2. Routing the connection
    3. Closing the connection gracefully

    Initial subscription -> renew subscription -> route connection -> close connection
### 1: Subscribing and subscription renewal
- every server client interaction will start with an initial subscription message
- after that pub-sub window has reached it duration, the client will renew the subscription by passing the new subscription parameters
- the server then adjust the message publishing pattern based on the parameters passd by the client
- any server side action, such as going in with additional volume can also be passed in the subscription renewal, if so, the server will perform the proper action
- on a connection failure, this can be handle by the client simply reconnecting on a fresh subscription
    - there needs to be client and server side logic to make sure the data stays consistent in this case
    - edge cases to consider: brainstorming as I write this
        - client requests additional volume, connection is dropped. It is ambiguous as to if the order was executed or not
            - the same case applies for selling volume
        - conncection drops during a publishing window
            - server and client must realign at this point
            - a reconnect is needed
            - the server must have logic to recognize that this is an active symbol
            - client must re subscribe with no additional volume, and likely adjust the subscription window, perhaps the time the was left in the subscription window that was dropped
- subscriptions are renewed until the client determines that some other action is required, thus the logic is moved to another endpoint on the server
### 2: Routing the connection
- Given we have a closed system here, there is no logic required to publish the endpoints, though in an open server, this would be a valuable thing to have
- Then client will determine that it is time to move the entity into some new state
- at the end of a publishing window, the client will send a message to the server, dictating to move the connection to some other logical endpoint
- the client and server will then start exchanging messages regarding that logical state
- things to consider:
    - client side state machine needs to accurately enforce state boundaries
        - like if we are moving to start selling volume, ww should not have the ability to send a subscription related message
    - given this is a closed system, the logic on both the server and the client should be aligned in terms of possible actions that are taken in each state
- there should also be the ability to route back
### 3: CLosing the connection
- In the non failure case, the client should prompt the server to close the connection, to clean up any in memory resources
- client will send a message to server indicating that the session is over
- server will then close the connection
- client will wait to recieve a connection close response from the server
- then the client can clean up all resources associated with the entity


