# py-modem

### Docker Run Script
```
sudo docker run --restart unless-stopped --name modem-container --env WEBSOCKET_URI=wss://134.122.103.109/ws/ --env RECONNECT_DELAY=30 --env WS_KEY={change_to_real_key} --device=/dev/ttyXRUSB7 --device=/dev/ttyXRUSB6 --device=/dev/ttyXRUSB5 --device=/dev/ttyXRUSB4 --device=/dev/ttyXRUSB3 --device=/dev/ttyXRUSB2 --device=/dev/ttyXRUSB1 --device=/dev/ttyXRUSB0 py-modem
```