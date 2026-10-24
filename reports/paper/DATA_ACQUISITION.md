# Real-World Dataset Acquisition Guide

This guide specifies download sources, licenses, expected directory layouts, and CLI flags for the four benchmark induction motor datasets supported by the validation pipeline (`backend/app/validation/loaders/`).

To evaluate the digital twin against measured physical machinery, download at least one dataset and extract its contents into the corresponding directory under `data/`.

---

## 1. Summary of Supported Datasets

| Dataset Key (`--dataset`) | Name / Reference | Public URL | License | Key Modalities | Default `--data-root` |
|---|---|---|---|---|---|
| `bruinsma` | NLN-EMP (Bruinsma et al., *Data in Brief* 2024) | [4TU.ResearchData](https://data.4tu.nl/datasets/2b61183e-c14f-4131-829b-cc4822c369d0) | CC0 1.0 Universal | 3-phase current, 3-phase voltage, 5-axis accelerometers (20 kHz) | `data/bruinsma/` |
| `liman_c` | LIMAN-C Induction Motor Faults | [Mendeley Data kccmrf3864](https://data.mendeley.com/datasets/kccmrf3864/1) | CC BY 4.0 | 3-phase stator current (4,096 Hz, 16k samples/run) | `data/liman_c/` |
| `estogu` | ESTOGU Multimodal Motor Dataset | [Zenodo 18222578](https://zenodo.org/records/18222578) | Open / Check Record | Current, voltage, vibration; inverter and grid (50 Hz) | `data/estogu/` |
| `usp_brb` | USP Broken Rotor Bar (Treml et al., 2020) | [IEEE DataPort](https://ieee-dataport.org/open-access/experimental-database-detecting-and-diagnosing-rotor-broken-bar-three-phase-induction) | Open Access (Free login) | Currents & Voltages (50 kHz), Vibration (7.6 kHz) | `data/usp_brb/` |

---

## 2. Detailed Dataset Specifications

### A. Bruinsma (`--dataset bruinsma`)
* **Reference:** Bruinsma et al., *"Motor current and vibration monitoring dataset for various faults in an E-motor-driven centrifugal pump"*, Data in Brief 52 (2024) 109987.
* **Download:** [4TU.ResearchData Dataset 2b61183e-c14f-4131-829b-cc4822c369d0](https://data.4tu.nl/datasets/2b61183e-c14f-4131-829b-cc4822c369d0). Single `.7z` archive (~20.8 GB).
* **License:** CC0 1.0 Universal (Public Domain).
* **Expected Directory Layout:**
  ```text
  data/bruinsma/
  ├── <measurement_folder_1>/
  │   ├── <measurement_base_name>_1.csv
  │   ├── <measurement_base_name>_2.csv
  │   └── ...
  └── <measurement_folder_2>/
  ```
  Folder names encode method (`vibration` or `electrical`), motor (`Motor 2` or `Motor 4`), speed (`1500rpm`, `1800rpm`), fault type, and severity.
* **Execution Command:**
  ```bash
  python -m app.validation.run --dataset bruinsma --protocol all --data-root data/bruinsma --seeds 0 1 2 3 4 --out reports/paper/real_bruinsma
  ```

---

### B. LIMAN-C (`--dataset liman_c`)
* **Reference:** LIMAN-C: Three-phase induction-motor current measurements under multiple fault and load conditions. Mendeley Data, doi:10.17632/kccmrf3864.1.
* **Download:** [Mendeley Data Repository](https://data.mendeley.com/datasets/kccmrf3864/1).
* **License:** Creative Commons Attribution 4.0 International (CC BY 4.0).
* **Characteristics:** 480 3-phase parent recordings across 4 motor condition groups (Healthy, Rotor Bar Defect, Bearing Defect, Inter-Turn Short). Stator current only.
* **Expected Directory Layout:**
  ```text
  data/liman_c/
  ├── Healthy/
  │   ├── H_load0_phaseA.csv
  │   └── ...
  ├── Rotor_Bar_Defect/
  ├── Bearing_Defect/
  └── Inter_Turn_Short/
  ```
* **Execution Command:**
  ```bash
  python -m app.validation.run --dataset liman_c --protocol all --data-root data/liman_c --seeds 0 1 2 3 4 --out reports/paper/real_liman_c
  ```

---

### C. ESTOGU (`--dataset estogu`)
* **Reference:** Multimodal motor condition monitoring dataset for fault diagnosis in electrical machines, Eskisehir Technical University.
* **Download:** [Zenodo Record 18222578](https://zenodo.org/records/18222578).
* **License:** Review repository record upon download.
* **Expected Directory Layout:**
  ```text
  data/estogu/
  ├── With_Driver/
  │   ├── N/
  │   ├── BB/
  │   ├── BR/
  │   ├── RB3/
  │   ├── RB5/
  │   └── SW/
  └── Without_Driver/
      └── ...
  ```
* **Execution Command:**
  ```bash
  python -m app.validation.run --dataset estogu --protocol all --data-root data/estogu --seeds 0 1 2 3 4 --out reports/paper/real_estogu
  ```

---

### D. USP Rotor Broken Bar (`--dataset usp_brb`)
* **Reference:** Treml, Flauzino, Suetake, Maciejewski (2020), *"Experimental database for detecting and diagnosing rotor broken bar in a three-phase induction motor"*, IEEE DataPort, doi:10.21227/fmnm-bn95.
* **Download:** [IEEE DataPort](https://ieee-dataport.org/open-access/experimental-database-detecting-and-diagnosing-rotor-broken-bar-three-phase-induction) (Free account required).
* **License:** IEEE DataPort Open Access.
* **Expected Directory Layout:**
  ```text
  data/usp_brb/
  ├── struct_rs_R1.mat
  ├── struct_r1b_R1.mat
  ├── struct_r2b_R1.mat
  ├── struct_r3b_R1.mat
  └── struct_r4b_R1.mat
  ```
* **Execution Command:**
  ```bash
  python -m app.validation.run --dataset usp_brb --protocol all --data-root data/usp_brb --seeds 0 1 2 3 4 --out reports/paper/real_usp_brb
  ```
