# torchat

## Pre requisites



# Part 1
## How to convert wif to Onion Address
## Download TOR Key Converter

[📥 Download tor-key-converter.html](https://github.com/ranchimall/torchat/blob/main/tor-key-converter.html)

## Open the html in a browser:
Enter your FLO or BTC blockchain wif, Click button: "Convert WIF → Tor Keys", and it will download three files:
1. hostname
2. hs_ed25519_public_key
3. hs_ed25519_secret_key

# Part 2
## How to setup TOR from the generated secret key
## Step 1: Download TOR browser
[📥 Download TOR browser](https://www.torproject.org/download/)

## Step 2. Find tor.exe
It is usually located at:
C:\Users\<YourUser>\Desktop\Tor Browser\Browser\TorBrowser\Tor\tor.exe
or
C:\Program Files\Tor Browser\Browser\TorBrowser\Tor\tor.exe

## Verify that you have:
tor.exe
and
torrc-defaults

## Step 3. Create a torrc file
In the same directory as tor.exe, create a file called:
torrc

The extension of the file will be nothing, only torcc
![torcc file Screenshot](torcc_screenshot.png)

## Enter these values inside the new torcc file
HiddenServiceDir C:\TorHiddenService
HiddenServicePort 80 127.0.0.1:8765
HiddenServiceVersion 3
SocksPort 9050

## Save it

## Step 4. Create the directory TorHiddenService

Create a folder
C:\TorHiddenService

## Very important
Copy your generated secret key from Part 1 inside TorHiddenService
C:\TorHiddenService\hs_ed25519_secret_key

## Step 5. Start Tor
Open CMD.

Go to the Tor folder.

Example:
cd "C:\Program Files\Tor Browser\Browser\TorBrowser\Tor"

Run
tor.exe -f torrc

You'll see something similar to
Bootstrapped 100% (done)

## This will update your C:\TorHiddenService with
hostname
hs_ed25519_public_key
hs_ed25519_secret_key

# Part 3
## How to run the audio video chat app on TOR

## Step 1
## Download the standalone python code for the chat app
[📥 Download chat_app_av.py](https://github.com/ranchimall/torchat/blob/main/chat_app_av.py)

## Step 2
## Copy the python code in a path of your choice.
Example: C:\Users\<Your User>\Documents\TOR Chat\chat_app_av.py

## Step 3
## Run the python script
Open CMD.

Go to the Chat App folder.

Example:
C:\Users\<Your User>\Documents\TOR Chat

Run
python chat_app.py listen --port 8765 --video --audio

You will see a screen like this inside the terminal
![chat_app connecting screenshot](chat_app_connecting_screenshot.png)

## You are now waiting another peer to join your TOR chat connection

## Step 4
## Copy your hostname or Onion address
Go to C:\TorHiddenService
Open the file "hostname" with any note editor

## Your onion address is something like this with a .onion extension
xyikvsf3e55rqwdbhycxjurop6fmj7cs9du7jcb5khk67dxfy2tapuqid.onion

## Copy the onion address
## Send it to the peson or peer who wants to connect to your TOR chat network

## Step 5 (Very Important)
## Your peer will need to start TOR using the same command

CMD
cd "C:\Program Files\Tor Browser\Browser\TorBrowser\Tor"

Run
tor.exe -f torrc

## Step 6
## Once the TOR is connected (Bootstrapped 100% (done)
The peer will need to run this command to connect to your TOR chat network

python chat_app_av.py connect --onion <Your Onion Address .onion> --port 80 --video --audio

## TOR Chat is now connected
### Both you and the peer will see the chat window in the opened terminal.
### Your webcam will open
### A text based chat can be used inside the terminal running the chat_app_av.py command

## Note:
## In any case, the TOR must be always running to connect to the chat app 





