# TOR Video + Audio + Chat

A fully decentralized, peer-to-peer encrypted video and audio chat application that routes all traffic over the Tor network. 

## Prerequisites
1. **Python 3.8+**
2. **Tor** (the actual Tor daemon)
3. **Python packages** (see below)

### Python Packages
It is highly recommended to install the dependencies inside a Python virtual environment to avoid conflicting with your system packages.

1. **Create the virtual environment:**
   ```bash
   python -m venv venv
   ```

2. **Activate the virtual environment:**
   * **Windows:** `.\venv\Scripts\activate`
   * **Mac/Linux:** `source venv/bin/activate`

3. **Install the requirements:**
   Once your terminal shows `(venv)` at the prompt, run:
   ```bash
   pip install -r requirements.txt
   ```

### System Libraries
* **Windows:** The Opus DLL gets automatically set up if you run the automated script. Otherwise, you must use the manual setup below.
* **macOS:** `brew install opus`
* **Linux (Debian/Ubuntu):** `sudo apt install libopus0`

#### Alternative: Manual Opus Windows Setup
If you prefer to install the Opus DLL manually rather than using the auto-downloader, you can do so using MSYS2.

**1. Install Opus DLL using MSYS2**

Install MSYS2 from:
[https://www.msys2.org/](https://www.msys2.org/)

Open the **MSYS2 MINGW64** terminal and run:
```bash
pacman -S mingw-w64-x86_64-opus
```

This installs:
```
C:\msys64\mingw64\bin\libopus-0.dll
```

**2. Configure the application**

If the application cannot automatically locate the Opus library, edit:
```
Python\Lib\site-packages\opuslib\api\__init__.py
```

Replace:
```python
lib_location = find_library("opus")

if lib_location is None:
    raise Exception(
        "Could not find Opus library. Make sure it is installed.")

libopus = ctypes.CDLL(lib_location)
```

with:
```python
lib_location = find_library("opus")

# Windows fallback
if lib_location is None:
    lib_location = r"C:\msys64\mingw64\bin\libopus-0.dll"

libopus = ctypes.CDLL(lib_location)
```

**3. Verify**

Run:
```bash
python -c "import opuslib; print('Opus loaded successfully')"
```

If you see:
```
Opus loaded successfully
```
then the audio dependency has been installed correctly.

---

# Setup Guide

## Part 1: Automated Tor Setup (Keys & Hidden Service)
Setting up a Tor hidden service manually can be tedious. We have built a web-based **Tor Keys Generator** that automatically converts your private key (WIF) into valid Tor Hidden Service Keys and generates automated setup scripts.

**Live Link:** [https://ranchimall.github.io/PrivateKeyToTOR/](https://ranchimall.github.io/PrivateKeyToTOR/)

### Steps:
1. Open the live link above in your browser.
2. Enter your FLO or BTC blockchain WIF (or click "Generate New Keys" if you don't have one).
3. Click the button to convert your WIF to Tor Keys.
4. Scroll down to the ** Automated Setup Scripts** section.
5. Click on **Windows**, **Mac OS**, or **Linux** to download your customized setup script (`.bat` or `.sh`).
6. Run the downloaded script on your computer. It will automatically:
   * Install the Tor background daemon.
   * Create your `torrc` file with the correct Hidden Service mapping.
   * Place your newly generated Tor Keys into the correct folders automatically.
   * Print out your final `.onion` address.

## Part 2: How to setup TOR from the downloaded secret key
### Step 1: Download TOR browser
[📥 Download TOR browser](https://www.torproject.org/download/)

### Step 2. Find tor.exe
It is usually located at:
C:\Users\<YourUser>\Desktop\Tor Browser\Browser\TorBrowser\Tor\tor.exe
or
C:\Program Files\Tor Browser\Browser\TorBrowser\Tor\tor.exe

### Verify that you have:
tor.exe
and
torrc-defaults

### Step 3. Create a torrc file
In the same directory as tor.exe, create a file called:
torrc

The extension of the file will be nothing, only torcc
![torcc file Screenshot](torcc_screenshot.png)

### Enter these values inside the new torcc file
HiddenServiceDir C:\TorHiddenService
HiddenServicePort 80 127.0.0.1:8765
HiddenServiceVersion 3
SocksPort 9050

### Save it

### Step 4. Create the directory TorHiddenService

Create a folder
C:\TorHiddenService

## Very important (Downloading your Keys)
Go to the **Manual Configuration** section on the [Tor Keys Generator](https://ranchimall.github.io/PrivateKeyToTOR/) website and click the **"Download Backup Keys"** button. 

Extract the downloaded files and copy your `hs_ed25519_secret_key` into the TorHiddenService folder you just created:
C:\TorHiddenService\hs_ed25519_secret_key

### Step 5. Start Tor
Open CMD.

Go to the Tor folder.

Example:
cd "C:\Program Files\Tor Browser\Browser\TorBrowser\Tor"

Run
tor.exe -f torrc

You'll see something similar to
Bootstrapped 100% (done)

### This will update your C:\TorHiddenService with
hostname
hs_ed25519_public_key
hs_ed25519_secret_key

---

# Part 3: How to run the Audio/Video Chat

### Step 1: Start Tor
Ensure your Tor background service is running. If you used the automated setup script from Part 1, it will start Tor for you automatically.

### Step 2: The Host (Listener)
If you are hosting the chat, you need to run the script in `listen` mode. 

Open your terminal in the directory containing `chat_app_av.py` and run:
```bash
python chat_app_av.py listen --port 8765 --video --audio
```
*You will see a waiting screen. Your webcam will initialize.*

### Step 3: Share your Onion Address
Give the `.onion` address (generated in Part 1) to your friend. 

### Step 4: The Peer (Connector)
Your friend will use your `.onion` address to connect to you. They must also have Tor running in the background.

They run:
```bash
python chat_app_av.py connect --onion YOUR_ONION_ADDRESS.onion --port 80 --video --audio
```
*(Replace `YOUR_ONION_ADDRESS.onion` with the actual address).*

### Step 5: Chat!
Once connected:
* **Video:** A video window will pop up. You can freely resize the video window by dragging the corners! Press `q` while focused on the window to quit.
* **Audio:** You can speak normally. If the audio is too loud or quiet, type `/vol <number>` (e.g. `/vol 6`) into the chat window to dynamically boost the volume multiplier.
* **Text:** A text-based chat can be used directly inside the terminal running the script. Type `/quit` to exit.
