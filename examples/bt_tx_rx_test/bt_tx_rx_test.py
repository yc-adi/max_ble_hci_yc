"""
TODO:
run the Bluetooth classic TX/RX test like:
TX side: Y3, Rev C
python src/max_ble_hci_cli.py /dev/serial/by-id/usb-FTDI_FT230X_Basic_UART_DT03OGQ4-if00-port0 -b 921600 -efc --stop-bit 2

RX side: Y1, Rev A
python src/max_ble_hci_cli.py /dev/serial/by-id/usb-FTDI_FT230X_Basic_UART_DT03NSU1-if00-port0 -b 921600 -efc --stop-bit 2

first run the RX side:
rxbtvs -c 38 -p 11

then run the TX side: 
txbtvs -c 38 --pt 11 -pl 1020 -s 10

after 12 seconds, run the RX side again to check the results:
endbtvs

Example results:
RX side:
>>> rxbtvs -c 38 -p 11
Parsing BT_RX_TEST
INFO - 2026-11-05 20:29:35.826398  DUT>0170fc03260b00
INFO - 2026-11-05 20:29:35.833805  DUT<040e040570fc00
StatusCode.SUCCESS
>>>
>>> endbtvs
Parsing BT_TEST_END
INFO - 2026-11-05 20:30:03.446382  DUT>0172fc00
INFO - 2026-11-05 20:30:03.448629  DUT<040e060572fc008402
(644, <StatusCode.SUCCESS: 0>)


TX side:
>>> txbtvs -c 38 --pt 11 -pl 1021 -s 10
Parsing BT_TX_TEST
INFO - 2026-11-05 20:29:44.375347  DUT>0171fc0726fd03000b0000
INFO - 2026-11-05 20:29:44.390120  DUT<040e040571fc00
StatusCode.SUCCESS
Running TX test for 10.0 s...
Parsing BT_TEST_END
INFO - 2026-11-05 20:29:54.406179  DUT>0172fc00
INFO - 2026-11-05 20:29:54.421209  DUT<040e060572fc00730a
(2675, <StatusCode.SUCCESS: 0>)

Calculate the packet error rate (PER) as follows:
PER = (number of packets lost / number of packets sent) * 100

1. test different packet types
2. with a packet type, test odd and even length of packet length
3. for each test, test 3 times 
4. try 3 channels (?, ?, and 38)

For the first version, only try one test first in the loop
"""

import argparse
import csv
import time

from max_ble_hci import BleHci
from max_ble_hci.packet_codes import StatusCode

# Serial ports of the two boards (see the notes above). Override with --tx-port / --rx-port.
TX_HCI_PORT = "/dev/serial/by-id/usb-FTDI_FT230X_Basic_UART_DT03OGQ4-if00-port0"
RX_HCI_PORT = "/dev/serial/by-id/usb-FTDI_FT230X_Basic_UART_DT03NSU1-if00-port0"

BAUD = 921600
STOP_BITS = 2
# Time between starting the RX test and starting the TX test, and after the TX test has ended
SETTLE_S = 1.0
# Extra time after the TX test ends before the RX test is ended
GUARD_S = 2.0


def open_hci(port, tag):
    """Open one board with the same settings as: -b 921600 -efc --stop-bit 2"""
    return BleHci(
        port,
        baud=BAUD,
        id_tag=tag,
        log_level="WARNING",
        timeout=2.0,
        flowcontrol=True,
        stopbits=STOP_BITS,
    )


def run_one(tx_hci, rx_hci, channel, pkt_type, pkt_len, seconds, tx_power):
    """Run one TX/RX test. Returns (tx_count, rx_count) or None on a command error."""
    # Start the RX side first, then the TX side
    status = rx_hci.rx_test_bt_vs(channel=channel, packet_type=pkt_type)
    if status != StatusCode.SUCCESS:
        print(f"RX start failed: {status}")
        return None
    time.sleep(SETTLE_S)

    status = tx_hci.tx_test_bt_vs(channel=channel, packet_len=pkt_len, packet_type=pkt_type, tx_power=tx_power)
    if status != StatusCode.SUCCESS:
        print(f"TX start failed: {status}")
        rx_hci.test_end_bt_vs()
        return None

    time.sleep(seconds)

    # Stop the TX side first, then the RX side
    tx_count, tx_status = tx_hci.test_end_bt_vs()
    time.sleep(GUARD_S)
    rx_count, rx_status = rx_hci.test_end_bt_vs()
    if tx_status != StatusCode.SUCCESS or rx_status != StatusCode.SUCCESS:
        print(f"Test end failed: TX {tx_status}, RX {rx_status}")
        return None
    return tx_count, rx_count


def per_percent(tx_count, rx_count):
    """PER = packets lost / packets sent * 100"""
    if tx_count == 0:
        return float("nan")
    return (tx_count - rx_count) / tx_count * 100.0


def main():
    """MAIN"""
    parser = argparse.ArgumentParser(description="Bluetooth Classic TX/RX packet error rate test")
    parser.add_argument("--tx-port", default=TX_HCI_PORT, help="Serial port of the TX board")
    parser.add_argument("--rx-port", default=RX_HCI_PORT, help="Serial port of the RX board")
    parser.add_argument("-c", "--channels", type=int, nargs="+", default=[38], help="Channels. Default: 38")
    parser.add_argument("--pt", dest="pkt_types", type=int, nargs="+", default=[11], help="Packet types (11 = 3DH5). Default: 11")
    parser.add_argument("-pl", "--lengths", type=int, nargs="+", default=[1021], help="Payload lengths. Default: 1021")
    parser.add_argument("-n", "--repeat", type=int, default=1, help="Runs per combination. Default: 1")
    parser.add_argument("-s", "--seconds", type=float, default=10, help="TX duration of each run in seconds. Default: 10")
    parser.add_argument("-t", "--tx-power", type=int, default=0, help="TX power in dBm. Default: 0")
    parser.add_argument("--csv", default="", help="Write the results to this CSV file")
    args = parser.parse_args()

    tx_hci = open_hci(args.tx_port, "TX")
    rx_hci = open_hci(args.rx_port, "RX")

    rows = []
    header = f"{'chan':>4} {'pt':>3} {'len':>5} {'run':>3} {'sent':>7} {'recv':>7} {'lost':>7} {'PER %':>7}"
    print(header)
    print("-" * len(header))

    for channel in args.channels:
        for pkt_type in args.pkt_types:
            for pkt_len in args.lengths:
                for run in range(1, args.repeat + 1):
                    result = run_one(tx_hci, rx_hci, channel, pkt_type, pkt_len, args.seconds, args.tx_power)
                    if result is None:
                        continue
                    tx_count, rx_count = result
                    per = per_percent(tx_count, rx_count)
                    rows.append([channel, pkt_type, pkt_len, run, tx_count, rx_count, tx_count - rx_count, round(per, 1)])
                    print(f"{channel:>4} {pkt_type:>3} {pkt_len:>5} {run:>3} {tx_count:>7} {rx_count:>7} {tx_count - rx_count:>7} {per:>7.1f}")

    if args.csv and rows:
        with open(args.csv, "w", newline="") as csv_file:
            writer = csv.writer(csv_file)
            writer.writerow(["channel", "pkt_type", "pkt_len", "run", "sent", "received", "lost", "per_percent"])
            writer.writerows(rows)
        print(f"Results written to {args.csv}")


if __name__ == "__main__":
    main()
