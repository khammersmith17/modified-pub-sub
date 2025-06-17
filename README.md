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
- when the message is a pub from the broker, the message wil be consumed and use in within the application logic
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

