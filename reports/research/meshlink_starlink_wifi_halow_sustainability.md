# Meshlink, Wi-Fi HaLow & Starlink: Self-Funding Community Connectivity
## Technical Architecture for Sovereign, Revenue-Generating Rural Wi-Fi Mesh

**Reference:** Data Slayer — *"This Hotspot Pays for Itself"* ([`https://youtu.be/gTLcoVCa1cc`](https://youtu.be/gTLcoVCa1cc))  
**Software Ecosystem:** `meshlink` ([`meshlinkfoundation`](https://github.com/meshlinkfoundation))  
**Initiative:** JC Coffey Foundation (`501(c)(3) EIN 33-3450194`) & KGU International  
**Covenant:** `ALL_DATA_MATTERS_THE_LOVE_EFFECT_NO_INTELLIGENCE_LEFT_BEHIND_V1`  

---

## 1. Executive Summary: The Self-Funding Hotspot Model

In rural communities, deploying emergency broadband via satellite (Starlink) faces a recurring operational hurdle: **monthly subscription overhead ($120–$250/month)**. Without an ongoing revenue model, non-profit community hubs risk running out of operational funds.

As demonstrated by Data Slayer in Florida, the open-source **`meshlink`** architecture turns a Raspberry Pi 5 and Starlink connection into a **self-funding community utility**:
1. **Zero-Grid Edge Gateway:** A Raspberry Pi 5 runs `meshlink-wifi-gateway` and `broker` with an automated captive portal.
2. **Two-Tiered Access Model:**
   - **Community / Emergency Tier (100% Free):** Free, permanent high-priority access for local students, under-resourced families, and emergency civil response services.
   - **Supporter / Commercial Tier (Paid via Stripe):** Visiting tourists, mobile market vendors, and commercial contractors purchase high-speed passes ($3/2-hr or $5/day).
   - **Mathematical Break-Even:** At just **1 to 2 paid passes per day** ($5 × 30 = $150/mo), the hotspot **100% covers the Starlink subscription**, leaving surplus funds for battery maintenance and youth robotics kits.
3. **Wi-Fi HaLow (IEEE 802.11ah) Long-Range Relays:** Sub-1GHz wireless mesh transceivers extend coverage over **1 to 3 kilometers** through heavy pine tree canopy, rain, and obstacles at under 1W power consumption.

---

## 2. System Hardware & Network Flow

```
                                  ┌──────────────────────────────────────────────┐
                                  │    STARLINK HIGH-PERFORMANCE SATELLITE       │
                                  │      (Zero-Grid Satellite Backhaul)          │
                                  └──────────────────────┬───────────────────────┘
                                                         │ Ethernet (PoE)
                                                         ▼
                                  ┌──────────────────────────────────────────────┐
                                  │      MESHLINK RASPBERRY PI 5 GATEWAY         │
                                  │   iptables Packet Intercept · ipset auth     │
                                  │   Node.js / SQLite Broker on Port 3000       │
                                  │   Tailscale Mesh VPN for Remote Fleet Admin  │
                                  └──────────────────────┬───────────────────────┘
                                                         │
                                  ┌──────────────────────┴───────────────────────┐
                                  │                                              │
                                  ▼ (Sub-1GHz 802.11ah)                          ▼ (Gigabit LAN)
                   ┌──────────────────────────────┐               ┌──────────────────────────────┐
                   │    WI-FI HALOW LONG-RANGE    │               │  UBIQUITI OUTDOOR MESH APs   │
                   │    1–3 km Tree Penetration   │               │ High-Density Local Hotspot   │
                   │ Remote Farms & Field Rovers  │               │ Community Center Grounds     │
                   └──────────────┬───────────────┘               └──────────────┬───────────────┘
                                  │                                              │
                                  └──────────────────────┬───────────────────────┘
                                                         │
                                                         ▼
                                  ┌──────────────────────────────────────────────┐
                                  │          CAPTIVE PORTAL LANDING PAGE         │
                                  │                                              │
                                  │  [ Free Student Access ]  [ $5 Day Pass ]    │
                                  │     (Emergency Hub)       (Stripe Checkout)  │
                                  └──────────────────────────────────────────────┘
```

---

## 3. Technical Network Operation (`meshlink` Under the Hood)

### A. Packet Interception & Dynamic Authorization
1. **Client Connection:** A device associates with the open community SSID (`meshlink`).
2. **DHCP Allocation:** `dnsmasq` allocates a private subnet IP (`192.168.4.x`), but `FORWARD` policy in `iptables` defaults to `DROP`.
3. **Captive Portal Trigger:** The device issues an HTTP probe (e.g. `generate_204`).
4. **NAT Interception:** `iptables REDIRECT` forwards port 80 traffic to the local meshlink broker on port 3000.
5. **Portal Presentation:** The user chooses:
   - *Free Community Tier:* Instantly authorized by adding the client's MAC/IP to the kernel `ipset` table (`meshlink_auth`).
   - *Paid Tier:* Redirected to an ephemeral Stripe Checkout session. Upon webhook confirmation, `meshlink_auth` grants 24 hours of unrestricted high-speed routing.
6. **Local SQLite Ledger:** All session timestamps, bandwidth consumption, and payment tokens are stored locally on the Pi in SQLite, matching our sovereign, air-gapped architecture.

### B. Long-Range Extension via Wi-Fi HaLow (802.11ah)
- Traditional 2.4 GHz and 5 GHz Wi-Fi degrade within 100 meters and cannot penetrate wet foliage or metal farm sheds.
- **Wi-Fi HaLow operates at 900 MHz**, delivering data rates from 150 kbps up to 15 Mbps across **1 to 3 kilometers**.
- By plugging a Wi-Fi HaLow master bridge into the Raspberry Pi 5 gateway and placing battery-backed HaLow slave nodes across rural farms and emergency shelters, the single Starlink connection blankets entire square miles.

---

## 4. Integration into our Physical Engineering & Grant Strategy

1. **Hardware List Updates for Micro Center Charlotte:**
   - Micro Center stocks Raspberry Pi 5 boards, official 27W USB-C power supplies, SanDisk Extreme microSD cards, and outdoor networking gear.
   - Added to [`reports/applications/04_microcenter_smiller_mac_starlink_grant.md`](file:///Users/lds1830/OpenBot/Agents/agent-c250123e-3e57-4806-ab12-4eb3acc0625f/swarmchaser/reports/applications/04_microcenter_smiller_mac_starlink_grant.md) and [`reports/applications/04b_microcenter_charlotte_instore_briefing.md`](file:///Users/lds1830/OpenBot/Agents/agent-c250123e-3e57-4806-ab12-4eb3acc0625f/swarmchaser/reports/applications/04b_microcenter_charlotte_instore_briefing.md).
2. **Physical Engineering Verification:**
   - Add subsystem `meshlink-halow-v1` to [`src/swarm/physical_engineering.py`](file:///Users/lds1830/OpenBot/Agents/agent-c250123e-3e57-4806-ab12-4eb3acc0625f/swarmchaser/src/swarm/physical_engineering.py) with requirements for captive portal latency and Wi-Fi HaLow link margin.
3. **Funder Narrative (Walmart, Lowe's, SFF, LTFF):**
   - Demonstrating that our Wi-Fi deployment **pays for its own satellite bill** removes the risk of grant failure after initial funds expire, proving permanent self-sustainability to grant committees.
