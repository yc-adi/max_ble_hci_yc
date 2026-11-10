#! /usr/bin/env python3
###############################################################################
#
#
# Copyright (C) 2023 Maxim Integrated Products, Inc., All Rights Reserved.
#
# Permission is hereby granted, free of charge, to any person obtaining a
# copy of this software and associated documentation files (the "Software"),
# to deal in the Software without restriction, including without limitation
# the rights to use, copy, modify, merge, publish, distribute, sublicense,
# and/or sell copies of the Software, and to permit persons to whom the
# Software is furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included
# in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS
# OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
# MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.
# IN NO EVENT SHALL MAXIM INTEGRATED BE LIABLE FOR ANY CLAIM, DAMAGES
# OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE,
# ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR
# OTHER DEALINGS IN THE SOFTWARE.
#
# Except as contained in this notice, the name of Maxim Integrated
# Products, Inc. shall not be used except as stated in the Maxim Integrated
# Products, Inc. Branding Policy.
#
# The mere transfer of this software does not imply any licenses
# of trade secrets, proprietary technology, copyrights, patents,
# trademarks, maskwork rights, or any other form of intellectual
# property whatsoever. Maxim Integrated Products, Inc. retains all
# ownership rights.
#
##############################################################################
#
# Copyright 2023 Analog Devices, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
##############################################################################
"""
full_test.py

Description: Full Bluetooth Classic TX/RX sweep between two devices. For every
             channel and ACL packet type, the test runs with an odd and an
             even packet length, repeated several times. The packet error rate
             (PER) of every run is appended to a CSV file.

Usage:
    python full_test.py TX_PORT RX_PORT [-b BAUD] [-efc] [--stop-bits N]
                        [--channels CH [CH ...]] [--packet-types PT [PT ...]]
                        [-r REPEATS] [-s SECONDS] [-o OUTPUT] [-t TX_POWER]

Examples:
    Full sweep (about 30 minutes):
        python full_test.py /dev/ttyUSB0 /dev/ttyUSB1 -b 921600 -efc \\
            --stop-bits 2 -o results.csv 2>&1 | tee full_test.log

    Quick check first (one channel, one packet type, one run, about 10 seconds):
        python full_test.py /dev/ttyUSB0 /dev/ttyUSB1 -b 921600 -efc \\
            --stop-bits 2 --channels 39 --packet-types 5 -r 1 -s 3 \\
            -o quick.csv
"""
import argparse
import csv
import sys
import time
from datetime import datetime

from max_ble_hci import BleHci
from max_ble_hci.constants import BtTxPacketType
from max_ble_hci.packet_codes import StatusCode

# Maximum user payload length (bytes) of each ACL packet type, per the
# Bluetooth Core Specification.
MAX_LENGTH = {
    BtTxPacketType.PKT_DM1: 17,
    BtTxPacketType.PKT_DH1: 27,
    BtTxPacketType.PKT_DM3: 121,
    BtTxPacketType.PKT_DH3: 183,
    BtTxPacketType.PKT_DM5: 224,
    BtTxPacketType.PKT_DH5: 339,
    BtTxPacketType.PKT_2DH1: 54,
    BtTxPacketType.PKT_3DH1: 83,
    BtTxPacketType.PKT_2DH3: 367,
    BtTxPacketType.PKT_3DH3: 552,
    BtTxPacketType.PKT_2DH5: 679,
    BtTxPacketType.PKT_3DH5: 1021,
}

CSV_COMMENTS = """\
# Bluetooth Classic TX/RX test results.
# Lines starting with '#' are comments.
#
# Column meanings:
#   timestamp        Local time the run finished (ISO 8601).
#   channel          Bluetooth Classic channel, 0-78 (frequency = 2402 + channel MHz).
#   packet_type      Packet type code sent to the device (BtTxPacketType value).
#   packet_type_name Packet type name, e.g. DM1, DH5, 3DH5.
#   packet_length    Payload length in bytes used for the run.
#   length_parity    odd or even, parity of packet_length.
#   run              Repeat index of this configuration, starting at 1.
#   tx_count         Packets reported as sent by the TX device.
#   rx_count         Packets reported as received by the RX device.
#   per_percent      Packet error rate = 100 * (1 - rx_count / tx_count). Empty if
#                    the run failed or tx_count is 0.
#   status           OK, or a short description of why the run failed.
#
"""
CSV_FIELDS = [
    "timestamp",
    "channel",
    "packet_type",
    "packet_type_name",
    "packet_length",
    "length_parity",
    "run",
    "tx_count",
    "rx_count",
    "per_percent",
    "status",
]


def _parse_args():
    parser = argparse.ArgumentParser(description=__doc__.strip().split("\n\n")[1])
    parser.add_argument("tx_port", help="TX board serial port path or COM#")
    parser.add_argument("rx_port", help="RX board serial port path or COM#")
    parser.add_argument("-b", "--baud", type=int, default=115200, help="Baud rate")
    parser.add_argument(
        "-efc", "--enable-flow-control", action="store_true", help="Enable flow control"
    )
    parser.add_argument("--stop-bits", type=int, default=1, help="Number of stop bits")
    parser.add_argument(
        "--channels",
        type=int,
        nargs="+",
        default=[0, 39, 78],
        help="Channels to test, 0-78 (default: 0 39 78)",
    )
    parser.add_argument(
        "--packet-types",
        type=int,
        nargs="+",
        default=[pt.value for pt in MAX_LENGTH],
        help="Packet type codes to test (default: all ACL types, 0-11)",
    )
    parser.add_argument(
        "-r", "--repeats", type=int, default=3, help="Runs per configuration"
    )
    parser.add_argument(
        "-s", "--seconds", type=float, default=5, help="Duration of each run"
    )
    parser.add_argument(
        "-p", "--payload", type=int, default=0, help="Payload pattern, 0: PRBS9"
    )
    parser.add_argument(
        "-t", "--tx-power", type=int, default=0, help="TX power, -127 to 20 dBm"
    )
    parser.add_argument("-o", "--output", default="results.csv", help="CSV file")
    args = parser.parse_args()

    valid = {pt.value for pt in MAX_LENGTH}
    bad = [pt for pt in args.packet_types if pt not in valid]
    if bad:
        parser.error(f"unsupported packet types {bad}, choose from {sorted(valid)}")
    if any(not 0 <= ch <= 78 for ch in args.channels):
        parser.error("channels must be in range 0-78")
    if args.repeats < 1 or args.seconds <= 0:
        parser.error("--repeats and --seconds must be greater than 0")
    return args


def _lengths(max_len):
    """Return the largest odd and the largest even length not above max_len."""
    odd = max_len if max_len % 2 else max_len - 1
    even = max_len if max_len % 2 == 0 else max_len - 1
    return [("odd", odd), ("even", even)]


def _run_once(rx_hci, tx_hci, args, channel, ptype, length):
    """Run one test. Returns (tx_count, rx_count, status_text)."""
    for name, hci in (("RX", rx_hci), ("TX", tx_hci)):
        status = hci.reset()
        if status != StatusCode.SUCCESS:
            return None, None, f"{name} reset failed: {status.name}"

    status = rx_hci.rx_test_bt_vs(channel=channel, packet_type=ptype)
    if status != StatusCode.SUCCESS:
        return None, None, f"RX start failed: {status.name}"

    status = tx_hci.tx_test_bt_vs(
        channel=channel,
        packet_len=length,
        payload=args.payload,
        packet_type=ptype,
        tx_power=args.tx_power,
    )
    if status != StatusCode.SUCCESS:
        rx_hci.test_end_bt_vs()
        return None, None, f"TX start failed: {status.name}"

    time.sleep(args.seconds)
    tx_count, tx_status = tx_hci.test_end_bt_vs()
    rx_count, rx_status = rx_hci.test_end_bt_vs()
    if tx_status != StatusCode.SUCCESS or rx_status != StatusCode.SUCCESS:
        return None, None, f"end failed: TX {tx_status.name}, RX {rx_status.name}"
    return tx_count, rx_count, "OK"


def main():
    """MAIN"""
    args = _parse_args()
    ptypes = [BtTxPacketType(pt) for pt in args.packet_types]
    total = len(args.channels) * len(ptypes) * 2 * args.repeats
    done = 0

    rx_hci = BleHci(
        args.rx_port,
        baud=args.baud,
        id_tag="RX",
        flowcontrol=args.enable_flow_control,
        stopbits=args.stop_bits,
    )
    tx_hci = BleHci(
        args.tx_port,
        baud=args.baud,
        id_tag="TX",
        flowcontrol=args.enable_flow_control,
        stopbits=args.stop_bits,
    )
    try:
        with open(args.output, "w", newline="", encoding="utf-8") as csv_file:
            csv_file.write(CSV_COMMENTS)
            writer = csv.DictWriter(csv_file, fieldnames=CSV_FIELDS)
            writer.writeheader()

            for channel in args.channels:
                for ptype in ptypes:
                    for parity, length in _lengths(MAX_LENGTH[ptype]):
                        for run in range(1, args.repeats + 1):
                            tx_count, rx_count, status = _run_once(
                                rx_hci, tx_hci, args, channel, ptype, length
                            )
                            per = ""
                            if status == "OK" and tx_count > 0:
                                per = f"{max(0.0, 100 * (1 - rx_count / tx_count)):.2f}"
                            elif status == "OK":
                                status = "TX reported 0 packets"
                            writer.writerow(
                                {
                                    "timestamp": datetime.now().isoformat(
                                        timespec="seconds"
                                    ),
                                    "channel": channel,
                                    "packet_type": ptype.value,
                                    "packet_type_name": ptype.name[4:],
                                    "packet_length": length,
                                    "length_parity": parity,
                                    "run": run,
                                    "tx_count": "" if tx_count is None else tx_count,
                                    "rx_count": "" if rx_count is None else rx_count,
                                    "per_percent": per,
                                    "status": status,
                                }
                            )
                            csv_file.flush()
                            done += 1
                            print(
                                f"[{done}/{total}] ch={channel} {ptype.name[4:]} "
                                f"len={length} run={run}: tx={tx_count} "
                                f"rx={rx_count} PER={per or 'n/a'} ({status})"
                            )
    finally:
        tx_hci.port.close()
        rx_hci.port.close()

    print(f"Results saved to {args.output}")


if __name__ == "__main__":
    sys.exit(main())
