# Production Client Deployment & Setup Guide
**5-Market Sports Prediction Engine, Admin Dashboard & Telegram Dispatcher**

This package contains the pre-built, production-ready Docker container image and deployment instructions to launch the 24/7 sports prediction system and Admin Portal on any Linux/Cloud server (AWS EC2, DigitalOcean, Hetzner, GCP, or local host).

---

## 📦 Package Contents

1. **`mario_ai_image.tar`**: Pre-compiled, fully self-contained Docker container image (Python 3.11, C++ XGBoost bindings, Polars engine, FastAPI Admin Dashboard, and 5 trained production models in `production_models/`).
2. **`docker-compose.yml`**: Production service orchestration for PostgreSQL database and live worker + web dashboard (Exposing Port 8000).
3. **`.env`**: Environment configuration template for API keys, Bot tokens, Telegram Channel IDs, and Admin Dashboard password.

---

## 🚀 Quick Start Deployment (3 Commands)

### Step 1: Load the Docker Image Archive
Upload `mario_ai_image.tar` to your server and run:
```bash
docker load -i mario_ai_image.tar
```
*Output: `Loaded image: marioaicode-app:latest`*

---

### Step 2: Configure Environment Credentials (`.env`)
Create or edit the `.env` file in your deployment directory with your credentials:

```env
# Database Connection
DATABASE_URL=postgresql://postgres:postgrespassword@db:5432/mario_ai

# External Odds API Credentials
JARBET_API_KEY=your_jarbet_api_key_here
JARBET_BASE_URL=https://data.jarvisbet.com.br

# Telegram Bot Token & Channel Chat IDs
TELEGRAM_BOT_TOKEN=8811681845:AAFVsEsCAupWgTYQNkLejO4Rt_eESJHbTAA
TELEGRAM_CHANNEL_FIFA_GOALS=-1004313543662
TELEGRAM_CHANNEL_FIFA_AH=-1004348571185
TELEGRAM_CHANNEL_FIFA_ML=-1003923100342
TELEGRAM_CHANNEL_EBASKET_ML=-1004263450744
TELEGRAM_CHANNEL_EBASKET_OU=-1004452838653

# Kickoff Window Calibration Parameters (Minutes Before Kickoff)
PRIMARY_KICKOFF_MINS_MIN=1.0
PRIMARY_KICKOFF_MINS_MAX=5.0
TARGET_KICKOFF_MINS=3.0

# Admin Dashboard Security
ADMIN_USERNAME=admin
ADMIN_PASSWORD=adminpassword
```

---

### Step 3: Launch Live Production Containers & Admin Dashboard
In the same directory containing `.env` and `docker-compose.yml`, run:

```bash
docker compose up -d
```

---

## 🖥️ How to Access the Admin Management Dashboard

Once the container is running, the Admin Portal is available immediately on Port `8000`:

* **Dashboard URL**: `http://your-server-ip:8000` (or `http://localhost:8000` for local access)
* **Default Username**: `admin`
* **Default Password**: `adminpassword` *(Configurable in `.env` via `ADMIN_PASSWORD`)*
* **Authentication**: Password protected HTTP session auth (No separate invitation needed).

### Dashboard Display Capabilities:
1. **Market Pipelines & Container Status**: Real-time status indicators (OPERATIONAL) for all 5 market models (FIFA Goals O/U, FIFA AH, FIFA ML, eBasketball ML, eBasketball O/U).
2. **Live Generated Tips Audit Table**: Displays fixture names, picks, bookmaker odds, calculated model edge %, recommended Quarter-Kelly stake, publication delivery status (`PUBLISHED`, `FILTERED`, `ERROR`), and microsecond timestamps.
3. **Direct Match Betting Links**: Action column contains sleek `[Bet Link]` buttons routing directly to the exact match and bookmaker event page.
4. **Real-Time Execution Console**: Live terminal log stream showing 30-second polling status, quality filtering metrics, and Telegram dispatch results.

---

## 📊 Live Monitoring & Commands

### View Real-Time Live Logs via CLI
```bash
docker compose logs -f app
```

### View Database Container Status
```bash
docker compose ps
```

### Restart Service
```bash
docker compose restart app
```

### Stop Service
```bash
docker compose down
```

---

## 📱 Telegram Tip Format (With Direct Betting Links)

Tips are posted in clean, professional Markdown containing direct event hyperlinks:

```text
*NEW HIGH-VALUE TIP | FIFA GOALS O/U*

*Match*: `Real Madrid (PlayerA)` vs `Barcelona (PlayerB)`
*League*: `Esports GT League`
*Pick*: *Over 2.5 Goals*
*Odds*: `1.95`
*Model Edge*: `+14.2%`
*Recommended Stake*: `0.75 Units` (Quarter-Kelly)
*Kickoff Window*: ~3 Mins Before Kickoff
*Direct Bet Link*: [Click Here to Bet on Match](https://data.jarvisbet.com.br/match/12345)

_Bet Responsibly | Mario AI Production Suite_
```
