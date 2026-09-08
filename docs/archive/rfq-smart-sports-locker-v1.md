# RFQ: Autonomous Outdoor Smart Sports Locker System

**Project:** IceCommunity / JustSkate Smart Sports Infrastructure  
**Document Version:** v1.0  
**Date:** 2026-05-27  
**Prepared by:** Maksim Vasilenka, Minsk, Belarus  
**Type:** OEM/ODM Request for Quotation (RFQ)  

---

## 1) Executive Overview

We are building a premium outdoor smart sports locker network for public sports grounds in Belarus and CIS markets.  
Our product enables mobile-first short-term rental of sports equipment (basketballs, footballs, and related gear) with fully unattended operation.

We are selecting a long-term OEM/ODM manufacturing partner through a structured RFQ process.  
We would highly appreciate partnering with a team that can deliver:

- robust outdoor enclosure engineering;
- autonomous low-power system integration (solar + battery preferred);
- Linux-based IoT controller integration;
- prototype and pilot batch production;
- long-term scalable manufacturing support.

This RFQ is prepared to reduce unnecessary back-and-forth and support efficient technical/commercial alignment.

---

## 2) Company and Project Context

### 2.1 About Us

- Team: IceCommunity / JustSkate ecosystem
- Region: Belarus (initial), then CIS expansion
- Business model: revenue from equipment rental + advertising/branding surfaces on locker units
- Positioning: premium urban sports infrastructure product (not parcel locker, not postal terminal)

### 2.2 Deployment Roadmap (target)

- **Phase A - Prototype validation:** 1 unit 
- **Phase B - Pilot in Minsk:** 10-20 units (Spring 2027)
- **Phase C - Scale:** 200+ units/year (subject to pilot results)

### 2.3 What Success Looks Like

- Reliable all-season outdoor operation in Belarus climate
- Attractive premium appearance in public urban spaces
- Stable remote device control via our own backend
- Predictable unit economics for pilot and scale volumes

---

## 3) Scope of Supply

We would appreciate OEM/ODM support for:

- mechanical enclosure and industrial design adaptation;
- electronic architecture and component integration;
- Linux-based controller platform;
- connectivity module integration (LTE);
- production, QA, and pilot/manufacturing support;
- technical documentation package.

Our team will independently own and develop:

- mobile applications;
- backend/cloud platform;
- payment logic and integrations;
- rental business logic;
- analytics and orchestration layer.

---

## 4) Product Definition (Target Configuration)

### 4.1 Core Locker Format

- 3 front-facing compartments for sports balls/equipment
- optimized for basketballs, footballs, and similar form factor items
- front doors only, hidden hinges preferred
- anti-vandal enclosure and locking approach
- fence-mounted / suspended installation preferred (no ground pedestal if avoidable)
- modular architecture for future capacity expansion

### 4.2 Design Direction

- clean, modern, rounded industrial design
- premium visual quality suitable for urban public spaces
- minimal visible technical elements
- dedicated branded/ad surfaces (replaceable panel concept preferred)

### 4.3 Reference Design Language

Reference style is close to Equip Sport outdoor lockers (form language and UX philosophy), while product architecture and software ecosystem are fully independent.  
Reference URL: [https://equip.sport/](https://equip.sport/)

---

## 5) Environmental and Reliability Requirements

Locker units will operate outdoors year-round in Belarus climate conditions:

- rain, snow, high humidity;
- freezing winter temperatures;
- summer heat and UV exposure;
- public-space vandalism risk.

Target requirements:

- IP65 minimum preferred for outdoor use;
- anti-corrosion treatment target C4/C5 class (or equivalent justification);
- UV-resistant external materials/coatings;
- long-life operation with minimal field maintenance.

Please provide guaranteed operating ranges and tested limits:

- operating temperature range;
- storage temperature range;
- humidity range;
- ingress protection details;
- corrosion resistance method and standard.

---

## 6) Power Architecture Requirements

### 6.1 Preferred Operating Model

- fully autonomous operation without permanent 220V connection
- solar + battery architecture preferred
- low-power electronics strategy

### 6.2 Preferred Power Stack

- LiFePO4 battery system
- MPPT solar charge controller
- battery management/protection (BMS)
- remote battery telemetry
- winter-ready charging/discharging strategy

### 6.3 Information We Kindly Ask You to Share

- battery chemistry and model options;
- usable capacity and cycle life assumptions;
- expected autonomy (days) under typical and low-sun scenarios;
- recommended solar panel wattage (target corridor 200-300W if feasible);
- low-temperature performance strategy;
- maintenance interval expectations.

---

## 7) Controller, Software Boundary, and Connectivity

### 7.1 Controller Requirements

Please propose controller/SBC options with:

- model and CPU;
- RAM/storage;
- supported Linux distribution;
- lifecycle/availability data;
- remote management capability.

### 7.2 Operating System and Access

- Linux-based environment is strongly preferred for seamless integration
- SSH/root access is highly appreciated for independent engineering maintenance
- preferably no hard dependency on vendor cloud for basic operation

### 7.3 Connectivity

- LTE primary connectivity
- auto-reconnect after network loss
- robust local fail-safe behavior in temporary offline mode

Please provide:

- modem model;
- supported LTE bands;
- SIM/eSIM options;
- reconnection logic details.

### 7.4 Integration Interfaces

- MQTT support is preferred for our target architecture
- REST API support is preferred for platform integration
- compatibility with our own MQTT broker and backend infrastructure is highly appreciated
- ability to implement MQTT event/command protocol based on our specification is appreciated

### 7.5 OTA and Device Management

Please describe:

- OTA update mechanism;
- rollback strategy in case of failed update;
- who controls release pipeline;
- whether vendor servers can be bypassed/disabled by customer choice.

---

## 8) Sensor Requirements

Please provide proposed sensor stack and specifications for:

- weight detection (type, precision, calibration method);
- door state sensing;
- battery voltage/current/SOC monitoring;
- internal temperature monitoring;
- humidity monitoring.

Include expected drift behavior and calibration/service procedures.

---

## 9) Security and Data Protection Expectations

Please describe your baseline security model for embedded and connectivity layers:

- TLS support for data-in-transit;
- credential/key storage approach;
- device authentication method;
- role-based access control (if supported);
- local data protection/encryption capabilities;
- secure behavior in offline mode.

---

## 10) Mechanical Architecture and Serviceability

Please confirm feasibility of technical compartment relocation:

- top or bottom service compartment variants;
- impact on maintenance access and MTTR;
- impact on thermal behavior and weather protection.

Please describe:

- lock and hinge durability strategy;
- anti-vandal design measures;
- field-service access design;
- spare parts strategy.

---

## 11) Branding and Advertising Module Requirements

Our business model includes ad/branding monetization on device surfaces.  
Please confirm support for:

- replaceable branding/advertising panel modules;
- panel material options (acrylic/metal/polycarbonate);
- mounting method and replacement workflow;
- panel production ownership (vendor vs customer-supplied);
- replacement without full unit disassembly.

---

## 12) IP, Ownership, and Rights (Important)

We would appreciate your clear position on:

- ownership of industrial design and CAD deliverables;
- ownership/licensing model for firmware and source/binary deliverables;
- customer rights to independently modify software/firmware;
- access rights to hardware/software documentation;
- restrictions (if any) on future dual-sourcing or manufacturing scale with other contractors.

If your standard model differs between OEM and ODM, please provide both variants.

---

## 13) Commercial Information Kindly Requested

To support fair comparison across vendors, we would appreciate your pricing and commercial details:

### 13.1 Unit Price Tiers (EXW preferred, specify currency)

- prototype (1 units);
- small batch (10 units);
- pilot batch (20-50 units);
- volume scenario (100 units);
- scale scenario (200+ units/year indicative).

### 13.2 NRE / Tooling / Customization Costs

- industrial design customization fee;
- tooling/mold costs (if applicable);
- firmware customization cost;
- certification/testing cost components.

### 13.3 Lead Times

- engineering proposal lead time;
- prototype lead time;
- pilot batch lead time;
- mass production lead time.

### 13.4 Terms

- MOQ by configuration;
- warranty terms;
- payment terms;
- incoterms options;
- after-sales support model and response SLA.

---

## 14) Suggested Response Format

If convenient, please respond using the table below to help us compare vendors consistently.


| ID  | Topic                                                                            | Vendor Response |
| --- | -------------------------------------------------------------------------------- | --------------- |
| 1   | Proposed controller/SBC (model, CPU, RAM, OS)                                    |                 |
| 2   | OS model and SSH/root availability                                               |                 |
| 3   | MQTT support and custom protocol implementation                                  |                 |
| 4   | LTE modem model, bands, auto-reconnect logic                                     |                 |
| 5   | Technical compartment placement options and service impact                       |                 |
| 6   | Fully autonomous solar-only feasibility                                          |                 |
| 7   | Battery/solar stack (chemistry, capacity, autonomy, MPPT, lifecycle, temp range) |                 |
| 8   | Corrosion protection class (C4/C5/equivalent)                                    |                 |
| 9   | Guaranteed outdoor IP rating                                                     |                 |
| 10  | Weight sensor type, precision, calibration approach                              |                 |
| 11  | IP/ownership terms (design, CAD, firmware, docs, future scaling rights)          |                 |
| 12  | OEM/ODM long-term scaling economics (10/100/200+ units)                          |                 |
| 13  | OTA approach (rollback, control ownership, server dependency)                    |                 |
| 14  | Security model (TLS, auth, RBAC, storage, offline mode)                          |                 |
| 15  | Branding/ad panel implementation and replacement workflow                        |                 |


---

## 15) What We Kindly Request from the Vendor at This Stage

At this stage, we would greatly appreciate a complete written RFQ response that includes:

- confirmation of technical feasibility for the target outdoor autonomous locker concept;
- proposed technical architecture and component options aligned with this document;
- clear statement of supported customization scope (industrial design, enclosure, electronics, firmware/integration);
- structured commercial quotation (unit pricing by volume, MOQ, NRE/tooling, lead times, warranty, terms);
- transparent IP/ownership terms for design files, firmware/software access, and documentation;
- completed responses to all items in Section 15 (Vendor Response Table).

If NDA is required before sharing deeper implementation details, please provide your standard NDA template.

---

## 16) Contact

**Maksim Vasilenka**  
Project Lead, IceCommunity / JustSkate  
Minsk, Belarus  
Email: `maksim.vasilenka555@gmail.com`  
Phone/WhatsApp/WeChat: `+375296675389`