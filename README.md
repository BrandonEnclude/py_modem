# py-modem

### Docker Run Script
```
sudo docker run --restart unless-stopped --name modem-container --env WEBSOCKET_URI=ws://localhost:8000 --env RECONNECT_DELAY=30 --device=/dev/ttyXRUSB7 --device=/dev/ttyXRUSB6 --device=/dev/ttyXRUSB5 --device=/dev/ttyXRUSB4 --device=/dev/ttyXRUSB3 --device=/dev/ttyXRUSB2 --device=/dev/ttyXRUSB1 --device=/dev/ttyXRUSB0 py-modem
```

sudo docker run -it --name modem-container --env WEBSOCKET_URI=ws://localhost:8000 --env RECONNECT_DELAY=30 --device=/dev/ttyXRUSB7 --device=/dev/ttyXRUSB6 --device=/dev/ttyXRUSB5 --device=/dev/ttyXRUSB4 --device=/dev/ttyXRUSB3 --device=/dev/ttyXRUSB2 --device=/dev/ttyXRUSB1 --device=/dev/ttyXRUSB0 py-modem