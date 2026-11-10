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
bt_tx_rx_test.py

Description: Bluetooth Classic TX/RX test between two devices. One board
             transmits test packets, the other counts them, and the packet
             error rate (PER) is printed.

Usage:
    python bt_tx_rx_test.py TX_PORT RX_PORT [-b BAUD] [-efc] [--stop-bits N]
                            [-c CHANNEL] [--pt PACKET_TYPE] [-pl PACKET_LENGTH]
                            [-p PAYLOAD] [-t TX_POWER] [-s SECONDS]

Example:
    python bt_tx_rx_test.py /dev/ttyUSB0 /dev/ttyUSB1 -b 921600 -efc \\
        --stop-bits 2 -c 38 --pt 11 -pl 1020 -s 10 2>&1 | tee test.log
"""
import argparse
import sys
import time

from max_ble_hci import BleHci
from max_ble_hci.packet_codes import StatusCode


def _parse_args():
    parser = argparse.ArgumentParser(description=__doc__.strip().split("\n\n")[1])
    parser.add_argument("tx_port", help="TX board serial port path or COM#")
    parser.add_argument("rx_port", help="RX board serial port path or COM#")
    parser.add_argument("-b", "--baud", type=int, default=115200, help="Baud rate")
    parser.add_argument(
        "-efc", "--enable-flow-control", action="store_true", help="Enable flow control"
    )
    parser.add_argument("--stop-bits", type=int, default=1, help="Number of stop bits")
    parser.add_argument("-c", "--channel", type=int, default=0, help="Channel, 0-79")
    parser.add_argument(
        "--pt",
        dest="packet_type",
        type=int,
        default=0,
        help="Packet type, 0-21 (0: DM1, 5: DH5, 11: 3DH5). Same on TX and RX",
    )
    parser.add_argument(
        "-pl",
        "--packet-length",
        type=int,
        default=0,
        help="Payload length in bytes, must fit the packet type",
    )
    parser.add_argument(
        "-p", "--payload", type=int, default=0, help="Payload pattern, 0: PRBS9"
    )
    parser.add_argument(
        "-t", "--tx-power", type=int, default=0, help="TX power, -127 to 20 dBm"
    )
    parser.add_argument(
        "-s", "--seconds", type=float, default=10, help="Test duration in seconds"
    )
    return parser.parse_args()


def main():
    """MAIN"""
    args = _parse_args()
    if args.seconds <= 0:
        sys.exit("--seconds must be greater than 0")

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
        for name, hci in (("RX", rx_hci), ("TX", tx_hci)):
            status = hci.reset()
            if status != StatusCode.SUCCESS:
                sys.exit(f"{name} reset failed: {status}")

        # Start RX first so it is listening when TX starts.
        status = rx_hci.rx_test_bt_vs(
            channel=args.channel, packet_type=args.packet_type
        )
        if status != StatusCode.SUCCESS:
            sys.exit(f"RX test failed to start: {status}")

        status = tx_hci.tx_test_bt_vs(
            channel=args.channel,
            packet_len=args.packet_length,
            payload=args.payload,
            packet_type=args.packet_type,
            tx_power=args.tx_power,
        )
        if status != StatusCode.SUCCESS:
            rx_hci.test_end_bt_vs()
            sys.exit(f"TX test failed to start: {status}")

        time.sleep(args.seconds)
        tx_count, tx_status = tx_hci.test_end_bt_vs()
        rx_count, rx_status = rx_hci.test_end_bt_vs()
    finally:
        tx_hci.port.close()
        rx_hci.port.close()

    print(f"TX sent:     {tx_count} ({tx_status.name})")
    print(f"RX received: {rx_count} ({rx_status.name})")
    if tx_count > 0:
        print(f"PER: {100 * (1 - rx_count / tx_count):.2f} %")
    else:
        print("PER: n/a (TX reported 0 packets)")


if __name__ == "__main__":
    main()
