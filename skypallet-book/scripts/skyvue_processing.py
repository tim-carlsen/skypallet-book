# -*- coding: utf-8 -*-
# ---
# jupyter:
#   jupytext:
#     cell_metadata_filter: -all
#     custom_cell_magics: kql
#     text_representation:
#       extension: .py
#       format_name: percent
#       format_version: '1.3'
#       jupytext_version: 1.11.2
#   kernelspec:
#     display_name: skypallet
#     language: python
#     name: python3
# ---

# %%
import re
import numpy as np
from dataclasses import dataclass
import pandas as pd
import xarray as xr
import math


# ---------- core helpers ----------

def _to_float_or_nan(token: str) -> float:
    """
    Convert a numeric token like '021.3' or '/////' to float.
    Returns np.nan for missing fields.
    """
    t = token.strip()
    if t in ('////', '/////'):
        return math.nan
    try:
        return float(t)
    except ValueError:
        return math.nan


def tokenize_raw(raw: str):
    """
    Replace control chars (<32) with spaces and split on whitespace.
    Works for your example SkyVueRawData string.
    """
    cleaned = ''.join(ch if ord(ch) >= 32 else ' ' for ch in raw)
    return cleaned.split()

def _parse_height_token(token: str) -> float:
    """
    Convert a 5-character height field like '00074' or '/////' to meters.
    Returns np.nan if missing.
    """
    token = token.strip()
    if token == '/////' or token == '////':
        return math.nan
    try:
        # Manual: values are in meters or feet depending on configuration.
        # Assume meters here; if you ever switch to feet, convert: value * 0.3048.
        return float(token)
    except ValueError:
        return math.nan


def split_message_010_tokens(tokens):
    """
    Split token list into logical lines for Message 010.
    Returns a dict with line1..line10 and 'crc'.
    """
    # Line 1: header token like "CS0016010"
    line1 = tokens[0]
    idx = 1

    # Line 2: S+WA, tr, h1, h2, h3, h4, flags (7 tokens)
    line2 = tokens[idx:idx+7];  idx += 7
    # Line 3: sky condition d1 h1 d2 h2 d3 h3 d4 h4 d5 h5 (10 tokens)
    line3 = tokens[idx:idx+10]; idx += 10
    # Line 4: measurement params (10 tokens)
    line4 = tokens[idx:idx+10]; idx += 10
    # Line 5: mixing layers (6 tokens)
    line5 = tokens[idx:idx+6];  idx += 6
    # Line 6: depol / freezing / penetration / cloud LDR / temp (11 tokens)
    line6 = tokens[idx:idx+11]; idx += 11

    # Remaining tokens: 4 profile lines + CRC/footer.
    remainder = tokens[idx:]

    # Profile lines are very long hex strings; join consecutive hex tokens.
    def take_profile(remainder_list):
        prof_tokens = []
        while remainder_list and re.fullmatch(r'[0-9A-Fa-f]+', remainder_list[0]):
            prof_tokens.append(remainder_list.pop(0))
        profile_str = ''.join(prof_tokens)
        return profile_str, remainder_list

    line7, remainder = take_profile(remainder)
    line8, remainder = take_profile(remainder)
    line9, remainder = take_profile(remainder)
    line10, remainder = take_profile(remainder)

    crc = remainder  # ETX, CRC-16, etc.

    return {
        'line1': line1,
        'line2': line2,
        'line3': line3,
        'line4': line4,
        'line5': line5,
        'line6': line6,
        'line7': line7,
        'line8': line8,
        'line9': line9,
        'line10': line10,
        'crc': crc,
    }
    

# ---------- decode 5-char hex profiles ----------

INT20_MAX_POS = 2**19 - 1
INT20_MOD     = 2**20

def decode_profile_hex(hex_array, scale_factor=1.0):
    raw = np.array([int(h, 16) for h in hex_array], dtype=np.int64)
    neg_mask = raw > INT20_MAX_POS
    raw[neg_mask] -= INT20_MOD
    return raw.astype(np.float64) * scale_factor

def decode_backscatter_profile_hex(hex_array, attenuated_scale_pct=100.0):
    """
    Decode 5-char hex samples to physical attenuated backscatter coefficient
    (sr^-1 m^-1), scaled by Attenuated_SCALE (%).
    """
    raw = np.array([int(h, 16) for h in hex_array], dtype=np.int64)

    # two's complement for 20-bit signed
    neg_mask = raw > INT20_MAX_POS
    raw[neg_mask] -= INT20_MOD

    # manual: multiply by 10^{-8}, then Attenuated_SCALE/100
    beta_att = raw.astype(np.float64) * 1e-8 * (attenuated_scale_pct / 100.0)
    return beta_att


def split_profile_string(profile_str: str, nbins: int):
    s = re.sub(r'\s+', '', profile_str)
    if len(s) < nbins * 5:
        raise ValueError(f"profile too short: got {len(s)} chars, need {nbins*5}")
    return [s[i:i+5] for i in range(0, nbins * 5, 5)]

def decode_cs_alarm_flags(flags_hex: str) -> dict:
    """
    Decode the 12-character flags field for CS messages (Tables 6-1, 6-2, 6-3).
    flags_hex example: '808000000000'

    Returns a dict of boolean flags keyed by descriptive names.
    """
    flags_hex = flags_hex.strip()
    if len(flags_hex) != 12:
        return {}

    try:
        msw = int(flags_hex[0:4], 16)   # Most significant word
        mid = int(flags_hex[4:8], 16)   # Middle word
        lsw = int(flags_hex[8:12], 16)  # Least significant word
    except ValueError:
        return {}

    out = {}

    # ----------------------------------------------------
    # Most significant word (Table 6-1, CS messages) <ref: index={29444793} firstWord={1} lastWord={25}/> / <ref: index={29444795} firstWord={1} lastWord={25}/>
    # ----------------------------------------------------
    # cxxx xxxx xxxx: units in meters AND precipitation detected
    out["units_meters_and_precip"] = bool((msw & 0xC000) == 0xC000)

    # 8000 XXXX XXXX: Units: feet = 0, meter = 1
    out["units_meters"] = bool(msw & 0x8000)

    # 4000 XXXX XXXX: Precipitation detected
    out["precipitation_detected"] = bool(msw & 0x4000)

    # 0800 XXXX XXXX: text truncated, but described as clock out of spec / DSP-related
    out["dsp_clock_out_of_spec"] = bool(msw & 0x0800)

    # 0400 XXXX XXXX: Laser shut down due to operating temperature out of range
    out["laser_shutdown_temp_out_of_range"] = bool(msw & 0x0400)

    # 0200 XXXX XXXX: Lead-acid battery voltage low
    out["lead_acid_battery_low"] = bool(msw & 0x0200)

    # 0100 XXXX XXXX: Mains supply has failed
    out["mains_supply_failed"] = bool(msw & 0x0100)

    # 0080 XXXX XXXX: External heater blower assembly temperature out of bounds
    out["ext_heater_blower_temp_out_of_bounds"] = bool(msw & 0x0080)

    # 0040 XXXX XXXX: External heater blower failure
    out["ext_heater_blower_failure"] = bool(msw & 0x0040)

    # ----------------------------------------------------
    # Middle word (Table 6-2, CS messages) <ref: index={29444794} firstWord={1} lastWord={25}/> / <ref: index={29444753} firstWord={1} lastWord={40}/> / <ref: index={29444800} firstWord={1} lastWord={25}/>
    # ----------------------------------------------------
    # XXXX 8000 XXXX: Sensor internal humidity is high
    out["internal_humidity_high"] = bool(mid & 0x8000)

    # XXXX 4000 XXXX: Comms to DSP temp/humidity chip have failed
    out["comms_dsp_th_failed"] = bool(mid & 0x4000)

    # XXXX 2000 XXXX: DSP input supply voltage is low
    out["dsp_input_voltage_low"] = bool(mid & 0x2000)

    # XXXX 1000 XXXX: Self-test active
    out["self_test_active"] = bool(mid & 0x1000)

    # XXXX 0800 XXXX: Watchdog counter updated
    out["watchdog_counter_updated"] = bool(mid & 0x0800)

    # XXXX 0400 XXXX: User settings in flash failed signature check
    out["user_settings_flash_bad"] = bool(mid & 0x0400)

    # XXXX 0200 XXXX: DSP factory calibration in flash failed signature check
    out["factory_cal_flash_bad"] = bool(mid & 0x0200)

    # XXXX 0100 XXXX: DSP-related fault (description truncated)
    out["dsp_flash_general_fault"] = bool(mid & 0x0100)

    # XXXX 0002 XXXX: Communications have failed between TOP board and DSP
    out["comms_top_dsp_failed"] = bool(mid & 0x0002)

    # XXXX 0001 XXXX: Photo diode background radiance out of range
    out["photodiode_background_out_of_range"] = bool(mid & 0x0001)

    # ----------------------------------------------------
    # Least significant word (Table 6-3, CS messages) <ref: index={29444754} firstWord={1} lastWord={25}/> / <ref: index={29444800} firstWord={1} lastWord={25}/>
    # ----------------------------------------------------
    # XXXX XXXX 8000: Photo diode temperature out of range
    out["photodiode_temp_out_of_range"] = bool(lsw & 0x8000)

    # XXXX XXXX 4000: Photo diode is saturated
    out["photodiode_saturated"] = bool(lsw & 0x4000)

    # XXXX XXXX 2000: Photo diode calibrator temperature out of range
    out["photodiode_cal_temp_out_of_range"] = bool(lsw & 0x2000)

    # XXXX XXXX 1000: Photo diode calibrator has failed
    out["photodiode_cal_failed"] = bool(lsw & 0x1000)

    # XXXX XXXX 0001: Laser is off
    out["laser_off"] = bool(lsw & 0x0001)

    return out


ALARM_FLAG_NAMES = [
    # Most significant word
    "units_meters_and_precip",
    "units_meters",
    "precipitation_detected",
    "dsp_clock_out_of_spec",
    "laser_shutdown_temp_out_of_range",
    "lead_acid_battery_low",
    "mains_supply_failed",
    "ext_heater_blower_temp_out_of_bounds",
    "ext_heater_blower_failure",
    # Middle word
    "internal_humidity_high",
    "comms_dsp_th_failed",
    "dsp_input_voltage_low",
    "self_test_active",
    "watchdog_counter_updated",
    "user_settings_flash_bad",
    "factory_cal_flash_bad",
    "dsp_flash_general_fault",
    "comms_top_dsp_failed",
    "photodiode_background_out_of_range",
    # Least significant word
    "photodiode_temp_out_of_range",
    "photodiode_saturated",
    "photodiode_cal_temp_out_of_range",
    "photodiode_cal_failed",
    "laser_off",
]



# ---------- line parsers for 010 ----------

@dataclass
class CSHeader:
    product: str
    sensor_id: str
    os: int
    msg: int

def parse_cs_header(token: str) -> CSHeader:
    assert token.startswith("CS")
    product = "CS"
    sensor_id = token[2]
    os = int(token[3:6])
    msg = int(token[6:9])
    return CSHeader(product, sensor_id, os, msg)

@dataclass
class CSStatusLine:
    detection_status: int
    wa: str
    window_trans_pct: int
    h1: str
    h2: str
    h3: str
    h4: str
    flags_hex: str

def parse_line2_status(tokens) -> CSStatusLine:
    # Example: ['10', '097', '00074', '/////', '/////', '/////', 'c00000000000']
    # In your string the first field is '10' (S=1, WA=0).
    s_wa = tokens[0]   # e.g. '10'
    S   = int(s_wa[0])
    WA  = s_wa[1]
    tr  = int(tokens[1])
    h1, h2, h3, h4 = tokens[2:6]
    flags_hex = ''.join(tokens[6:])  # usually one 12-char word
    return CSStatusLine(S, WA, tr, h1, h2, h3, h4, flags_hex)

def status_to_cloud_vars(status: CSStatusLine):
    """
    Interpret h1..h4 according to detection_status (S) into:
      - cloud_base_1_m ... cloud_base_4_m
      - vertical_visibility_m
    Based on SkyVue PRO documentation for h1..h4 and detection status.
    <ref: index={29444825} firstWord={1} lastWord={20}/>
    <ref: index={29444816} firstWord={1} lastWord={25}/>
    <ref: index={29444842} firstWord={1} lastWord={25}/>
    """
    S = status.detection_status
    h1 = _parse_height_token(status.h1)
    h2 = _parse_height_token(status.h2)
    h3 = _parse_height_token(status.h3)
    h4 = _parse_height_token(status.h4)

    cb1 = math.nan
    cb2 = math.nan
    cb3 = math.nan
    cb4 = math.nan
    vv  = math.nan

    # 1st height
    # If detection status is 1, 2, 3, or 4, h1 = Lowest cloud base reported
    # If detection status is 5, h1 = Vertical visibility as calculated
    # If detection status is 0 or 6, h1 = /////  <ref: index={29444816} firstWord={1} lastWord={25}/>
    if S in (1, 2, 3, 4):
        cb1 = h1
    elif S == 5:
        vv = h1  # vertical visibility

    # 2nd height
    # If detection status is 2, 3, or 4, h2 = Second cloud base reported
    # If detection status is 5, h2 = Highest signal received
    # If detection status is 0, 1, or 6, h2 = ///// <ref: index={29444816} firstWord={1} lastWord={25}/>
    if S in (2, 3, 4):
        cb2 = h2

    # 3rd height
    # If detection status is 3 or 4, h3 = Third cloud base reported
    # If detection status is 0, 1, 2, 5, or 6, h3 = ///// <ref: index={29444816} firstWord={1} lastWord={25}/>
    if S in (3, 4):
        cb3 = h3

    # 4th height
    # If detection status is 4, h4 = Fourth cloud base reported
    # If detection status is 0, 1, 2, 3, or 5, h4 = ///// <ref: index={29444819} firstWord={1} lastWord={20}/>
    if S == 4:
        cb4 = h4

    return {
        "cloud_base_1_m": cb1,
        "cloud_base_2_m": cb2,
        "cloud_base_3_m": cb3,
        "cloud_base_4_m": cb4,
        "vertical_visibility_m": vv,
    }


@dataclass
class SkyLayer:
    oktas_or_vv: int
    height: str

@dataclass
class CSSkyCondition:
    layers: list

def parse_line3_sky(tokens) -> CSSkyCondition:
    layers = []
    for i in range(0, min(len(tokens), 10), 2):
        d_str = tokens[i]
        h_str = tokens[i+1]
        if d_str.strip('/-') == '':
            d = -1
        else:
            d = int(d_str)
        layers.append(SkyLayer(oktas_or_vv=d, height=h_str))
    return CSSkyCondition(layers)

@dataclass
class CSMeasParams:
    scale: int
    range_res_m: int
    nbins: int
    energy_pct: int
    laser_temp_C: float
    tilt_deg: int
    background_mV: int
    pulse_count_x1000: int
    sample_rate_MHz: int
    backscatter_sum: int

def parse_line4_params(tokens) -> CSMeasParams:
    scale     = int(tokens[0])   # e.g. 00100
    res       = int(tokens[1])   # e.g. 05 m
    nbins     = int(tokens[2])   # e.g. 2048
    energy    = int(tokens[3])
    lt        = float(tokens[4])
    tilt      = int(tokens[5])
    bl        = int(tokens[6])
    pulse     = int(tokens[7])
    rate      = int(tokens[8])
    bsum      = int(tokens[9])
    return CSMeasParams(scale, res, nbins, energy, lt, tilt, bl, pulse, rate, bsum)

@dataclass
class CSMixingLayers:
    h1: str; q1: str
    h2: str; q2: str
    h3: str; q3: str

def parse_line5_mlh(tokens) -> CSMixingLayers:
    return CSMixingLayers(*tokens[0:6])

def mlh_to_vars(mlh: CSMixingLayers):
    """
    Convert mixing layer heights and quality field strings to floats.
    Based on LINE 4 MLH description (mh1_q1_mh2_q2_mh3_q3). <ref: index={29444839} firstWord={1} lastWord={20}/>
    """
    def _to_float(s):
        s = s.strip()
        if s == '/////' or s == '////':
            return math.nan
        try:
            return float(s)
        except ValueError:
            return math.nan

    return {
        "mlh1_m": _to_float(mlh.h1),
        "mlh1_quality": _to_float(mlh.q1),
        "mlh2_m": _to_float(mlh.h2),
        "mlh2_quality": _to_float(mlh.q2),
        "mlh3_m": _to_float(mlh.h3),
        "mlh3_quality": _to_float(mlh.q3),
    }

@dataclass
class CSDepolLine:
    d1: float
    l1: float
    d2: float
    l2: float
    d3: float
    l3: float
    d4: float
    l4: float
    ground_temp_C: float
    extra_fields: list

def parse_line6_depol(tokens) -> CSDepolLine:
    """
    Parse LINE 6 (depol / freezing / penetration / cloud LDR / ground temp).
    Layout (for Message 021 examples) is:

        D1 L1 D2 L2 D3 L3 D4 L4 G [ALR ...]

    where:
      - L1..L4 are cloud LDR values (dimensionless, often 1000*LDR in profile)
        and //// if missing
      - G is ground level air temperature in degC, or ///// if not present
        <ref: index={29444595} firstWord={1} lastWord={20}/>
    """
    # Pad with '/////' if shorter than expected
    toks = list(tokens) + ['/////'] * (9 - len(tokens))
    d1 = _to_float_or_nan(toks[0])
    l1 = _to_float_or_nan(toks[1])
    d2 = _to_float_or_nan(toks[2])
    l2 = _to_float_or_nan(toks[3])
    d3 = _to_float_or_nan(toks[4])
    l3 = _to_float_or_nan(toks[5])
    d4 = _to_float_or_nan(toks[6])
    l4 = _to_float_or_nan(toks[7])
    g  = _to_float_or_nan(toks[8])

    extra = tokens[9:] if len(tokens) > 9 else []

    return CSDepolLine(
        d1=d1, l1=l1,
        d2=d2, l2=l2,
        d3=d3, l3=l3,
        d4=d4, l4=l4,
        ground_temp_C=g,
        extra_fields=extra,
    )


# ---------- full 010 message decode ----------

def parse_cs_message_010(raw: str,
                         bs_scale_factor=1.0,
                         ldr_scale_factor=1.0,
                         par_scale_factor=1.0,
                         cross_scale_factor=1.0):
    """
    Parse one SkyVue Message 010 (your SkyVueRawData example) into fields + profiles.
    """
    tokens = tokenize_raw(raw)
    lines = split_message_010_tokens(tokens)

    header = parse_cs_header(lines['line1'])
    if header.msg != 10:
        raise ValueError(f"Not Message 010 (got msg={header.msg})")

    status = parse_line2_status(lines['line2'])
    sky    = parse_line3_sky(lines['line3'])
    meas   = parse_line4_params(lines['line4'])
    mlh    = parse_line5_mlh(lines['line5'])
    depol  = parse_line6_depol(lines['line6'])

    nbins = meas.nbins
    dz    = meas.range_res_m
    rng   = np.arange(nbins) * dz
    
    # Concatenate whatever we got for line7..10 and strip whitespace.
    hex_blob = re.sub(
        r'\s+',
        '',
        ''.join([lines['line7'], lines['line8'], lines['line9'], lines['line10']])
    )

    n_chars_per_profile = nbins * 5
    n_needed = n_chars_per_profile * 4

    if len(hex_blob) < n_needed:
        raise ValueError(
            f"Not enough hex for 4 profiles: have {len(hex_blob)} chars, "
            f"need {n_needed} (nbins={nbins})"
        )

    # Slice into 4 profiles; ignore anything beyond 4*nbins*5 (CRC tail)
    hex_bs   = hex_blob[0*n_chars_per_profile:1*n_chars_per_profile]
    hex_ldr  = hex_blob[1*n_chars_per_profile:2*n_chars_per_profile]
    hex_par  = hex_blob[2*n_chars_per_profile:3*n_chars_per_profile]
    hex_cross= hex_blob[3*n_chars_per_profile:4*n_chars_per_profile]

    lines['line7']  = hex_bs
    lines['line8']  = hex_ldr
    lines['line9']  = hex_par
    lines['line10'] = hex_cross

    prof_bs   = split_profile_string(lines['line7'], nbins)
    prof_ldr  = split_profile_string(lines['line8'], nbins)
    prof_par  = split_profile_string(lines['line9'], nbins)
    prof_cross= split_profile_string(lines['line10'], nbins)
    
    attenuated_scale_pct = meas.scale  # scale is Attenuated_SCALE parameter

    bs_total = decode_backscatter_profile_hex(prof_bs,  attenuated_scale_pct)
    bs_par   = decode_backscatter_profile_hex(prof_par, attenuated_scale_pct)
    bs_cross = decode_backscatter_profile_hex(prof_cross,attenuated_scale_pct)
    ldr_raw  = decode_profile_hex(prof_ldr, ldr_scale_factor)
    # LDR profile is similar 20-bit hex; manual says it's a linear depolarisation ratio profile
    # In practice, many OS versions store 1000 * LDR; if that’s the case:
    ldr = ldr_raw / 1000.0  # dimensionless depol ratio

    return {
        'header': header,
        'status': status,
        'sky':    sky,
        'meas':   meas,
        'mlh':    mlh,
        'depol':  depol,
        'range':  rng,
        'bs_total': bs_total,
        'ldr':      ldr,
        'bs_par':   bs_par,
        'bs_cross': bs_cross,
        'crc':   lines['crc'],
    }


# %%


def read_toa5_file(path):
    # Skip TOA5 headers, then parse data; adjust skiprows if needed
    df = pd.read_csv(path, skiprows=4, header=None)
    df.columns = ['timestamp', 'record', 'SkyVueRawData']
    # Keep only real messages (third column not "NAN")
    df = df[df['SkyVueRawData'] != 'NAN'].reset_index(drop=True)
    return df

def process_row_message010(row):
    msg = parse_cs_message_010(row['SkyVueRawData'])
    
    cloud_vars = status_to_cloud_vars(msg['status'])
    mlh_vars   = mlh_to_vars(msg['mlh'])
    alarm_flags = decode_cs_alarm_flags(msg['status'].flags_hex)

    return {
        'time': pd.to_datetime(row['timestamp']),
        'range': msg['range'],
        'bs_total': msg['bs_total'],
        'ldr': msg['ldr'],
        'bs_par': msg['bs_par'],
        'bs_cross': msg['bs_cross'],
        'meas': msg['meas'],
        'status': msg['status'],
        'sky': msg['sky'],
        'mlh': msg['mlh'],
        'depol': msg['depol'],
        **cloud_vars,
        **mlh_vars,
        'cloud_ldr_1': msg['depol'].l1,
        'cloud_ldr_2': msg['depol'].l2,
        'cloud_ldr_3': msg['depol'].l3,
        'cloud_ldr_4': msg['depol'].l4,
        'ground_temp_C': msg['depol'].ground_temp_C,
        'cloud_depth_1': msg['depol'].d1,
        'cloud_depth_2': msg['depol'].d2,
        'cloud_depth_3': msg['depol'].d3,
        'cloud_depth_4': msg['depol'].d4,
        'alarm_flags': alarm_flags,
    }




# %%
def build_dataset_from_file(path):
    df = read_toa5_file(path)

    times = []
    profiles_bs = []
    profiles_ldr = []
    profiles_par = []
    profiles_cross = []

    # We'll assume all rows in this file have same nbins / range_res
    range_coord = None

    # Optionally collect some scalar metadata per profile, e.g. background, energy
    energy_pct = []
    laser_temp = []
    window_trans = []
    
    detection_status = []
    wa_flag          = []
    cb1 = []; cb2 = []; cb3 = []; cb4 = []
    vv  = []
    mlh1 = []; mlh1_q = []
    mlh2 = []; mlh2_q = []
    mlh3 = []; mlh3_q = []
    
    cloud_ldr_1 = []; cloud_ldr_2 = []; cloud_ldr_3 = []; cloud_ldr_4 = []
    ground_temp_C = []
    cloud_depth_1 = []; cloud_depth_2 = []; cloud_depth_3 = []; cloud_depth_4 = []

    # Alarm flag time series
    alarm_series = {name: [] for name in ALARM_FLAG_NAMES}


    for _, row in df.iterrows():
        out = process_row_message010(row)

        times.append(out['time'])

        if range_coord is None:
            range_coord = out['range']  # 0, 5, 10, ... m

        profiles_bs.append(out['bs_total'])
        profiles_ldr.append(out['ldr'])
        profiles_par.append(out['bs_par'])
        profiles_cross.append(out['bs_cross'])

        energy_pct.append(out['meas'].energy_pct)
        laser_temp.append(out['meas'].laser_temp_C)
        window_trans.append(out['status'].window_trans_pct)

        detection_status.append(out['status'].detection_status)
        wa_flag.append(out['status'].wa)

        cb1.append(out['cloud_base_1_m'])
        cb2.append(out['cloud_base_2_m'])
        cb3.append(out['cloud_base_3_m'])
        cb4.append(out['cloud_base_4_m'])
        vv.append(out['vertical_visibility_m'])

        mlh1.append(out['mlh1_m'])
        mlh1_q.append(out['mlh1_quality'])
        mlh2.append(out['mlh2_m'])
        mlh2_q.append(out['mlh2_quality'])
        mlh3.append(out['mlh3_m'])
        mlh3_q.append(out['mlh3_quality'])
        
        cloud_ldr_1.append(out['cloud_ldr_1'])
        cloud_ldr_2.append(out['cloud_ldr_2'])
        cloud_ldr_3.append(out['cloud_ldr_3'])
        cloud_ldr_4.append(out['cloud_ldr_4'])
        ground_temp_C.append(out['ground_temp_C'])
        cloud_depth_1.append(out['cloud_depth_1'])
        cloud_depth_2.append(out['cloud_depth_2'])
        cloud_depth_3.append(out['cloud_depth_3'])
        cloud_depth_4.append(out['cloud_depth_4'])
        
        flags = out['alarm_flags']
        for name in ALARM_FLAG_NAMES:
            alarm_series[name].append(bool(flags.get(name, False)))


        data_vars = {
        'beta_att_total': (('time', 'range'), np.vstack(profiles_bs)),
        'ldr':            (('time', 'range'), np.vstack(profiles_ldr)),
        'beta_att_par':   (('time', 'range'), np.vstack(profiles_par)),
        'beta_att_cross': (('time', 'range'), np.vstack(profiles_cross)),
        'laser_energy_pct':  ('time', np.array(energy_pct)),
        'laser_temp_C':      ('time', np.array(laser_temp)),
        'window_trans_pct':  ('time', np.array(window_trans)),
        'detection_status':  ('time', np.array(detection_status, dtype=np.int16)),
        'wa_flag':           ('time', np.array(wa_flag, dtype='U1')),
        'cloud_base_1_m':    ('time', np.array(cb1, dtype=float)),
        'cloud_base_2_m':    ('time', np.array(cb2, dtype=float)),
        'cloud_base_3_m':    ('time', np.array(cb3, dtype=float)),
        'cloud_base_4_m':    ('time', np.array(cb4, dtype=float)),
        'vertical_visibility_m': ('time', np.array(vv, dtype=float)),
        'mlh1_m':           ('time', np.array(mlh1, dtype=float)),
        'mlh1_quality':     ('time', np.array(mlh1_q, dtype=float)),
        'mlh2_m':           ('time', np.array(mlh2, dtype=float)),
        'mlh2_quality':     ('time', np.array(mlh2_q, dtype=float)),
        'mlh3_m':           ('time', np.array(mlh3, dtype=float)),
        'mlh3_quality':     ('time', np.array(mlh3_q, dtype=float)),
        'cloud_ldr_1':      ('time', np.array(cloud_ldr_1, dtype=float)),
        'cloud_ldr_2':      ('time', np.array(cloud_ldr_2, dtype=float)),
        'cloud_ldr_3':      ('time', np.array(cloud_ldr_3, dtype=float)),
        'cloud_ldr_4':      ('time', np.array(cloud_ldr_4, dtype=float)),
        'ground_temp_C':    ('time', np.array(ground_temp_C, dtype=float)),
        'cloud_depth_1':    ('time', np.array(cloud_depth_1, dtype=float)),
        'cloud_depth_2':    ('time', np.array(cloud_depth_2, dtype=float)),
        'cloud_depth_3':    ('time', np.array(cloud_depth_3, dtype=float)),
        'cloud_depth_4':    ('time', np.array(cloud_depth_4, dtype=float)),
    }
        
        # Add alarm flags as boolean time series
        for name, series in alarm_series.items():
            data_vars[name] = ('time', np.array(series, dtype=bool))


    coords = {
        'time':  np.array(times),
        'range': range_coord,
    }

    ds = xr.Dataset(data_vars=data_vars, coords=coords)
    return ds


