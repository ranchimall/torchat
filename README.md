# torchat
## Part 1
## How to convert wif to Onion Address
## Download

[📥 Download tor-key-converter.html](https://github.com/ranchimall/torchat/blob/main/tor-key-converter.html)

Enter your wif and it will download three files:
1. hostname
2. hs_ed25519_public_key
3. hs_ed25519_secret_key

## part 2
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
