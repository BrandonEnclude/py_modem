# py-modem

### Docker Run Script
```
sudo docker run --restart unless-stopped --name modem-container --env WEBSOCKET_URI=wss://imugi.io/ws/ --env RECONNECT_DELAY=30 --env KEY=dev --device=/dev/ttyXRUSB7 --device=/dev/ttyXRUSB6 --device=/dev/ttyXRUSB5 --device=/dev/ttyXRUSB4 --device=/dev/ttyXRUSB3 --device=/dev/ttyXRUSB2 --device=/dev/ttyXRUSB1 --device=/dev/ttyXRUSB0 py-modem
```