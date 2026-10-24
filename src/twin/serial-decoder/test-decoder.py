import pytest

from decoder import (CrcError, DecodeError, PacketLayout, StreamDecoder,
                     crc16_ccitt_false)

NORMAL = {
    "heart_rate": 72, "respiration_rate": 15, "core_temp": 37.42, "skin_temp": 33.5,
    "perspiration": 4.25, "hydration_loss": 0.05, "spo2": 98, "o2": 20.9, "co2": 812,
    "suit_air_temp": 23.1, "vent_loop_temp": 20.0, "humidity": 42.5, "pm2_5": 5.3,
}


@pytest.fixture(scope="module")
def layout():
    return PacketLayout.from_yaml()


def test_crc_known_check_value():
    assert crc16_ccitt_false(b"123456789") == 0x29B1


def test_round_trip_applies_scaling(layout):
    frame = layout.encode_frame(NORMAL, seq=7)
    pkt = layout.decode_frame(frame)
    assert pkt.seq == 7
    assert pkt.readings["core_temp"].value == pytest.approx(37.42)
    assert pkt.readings["co2"].value == 812
    assert pkt.readings["pm2_5"].value == pytest.approx(5.3)
    assert all(r.quality == "ok" for r in pkt.readings.values())


def test_frame_length_matches_layout(layout):
    assert len(layout.encode_frame(NORMAL)) == layout.frame_len


def test_bad_crc_is_rejected(layout):
    frame = bytearray(layout.encode_frame(NORMAL))
    frame[10] ^= 0xFF
    with pytest.raises(CrcError):
        layout.decode_frame(bytes(frame))


def test_wrong_length_and_bad_sync_rejected(layout):
    frame = layout.encode_frame(NORMAL)
    with pytest.raises(DecodeError):
        layout.decode_frame(frame[:-1])
    with pytest.raises(DecodeError):
        layout.decode_frame(b"\x00\x00" + frame[2:])


def test_stale_suspect_and_fault_quality(layout):
    values = dict(NORMAL, heart_rate=300, core_temp=None)
    pkt = layout.decode_frame(layout.encode_frame(values, stale=["co2"]))
    assert pkt.readings["co2"].quality == "stale"
    assert pkt.readings["heart_rate"].quality == "suspect"   # 300 clamps to 255, above max 250
    assert pkt.readings["core_temp"].quality == "fault"
    assert pkt.readings["core_temp"].value is None


def test_stream_handles_garbage_and_split_chunks(layout):
    frames = [layout.encode_frame(NORMAL, seq=i) for i in range(3)]
    stream = b"\x01\x02\xaa" + b"".join(frames) # garbage, including a first sync byte
    dec = StreamDecoder(layout)
    packets = []
    for i in range(0, len(stream), 5): # arrives in tiny chunks
        packets += dec.feed(stream[i:i + 5])
    assert [p.seq for p in packets] == [0, 1, 2]
    assert dec.stats.bytes_skipped == 3


def test_stream_recovers_after_corrupted_frame(layout):
    f0, f1, f2 = (layout.encode_frame(NORMAL, seq=i) for i in range(3))
    bad = bytearray(f1)
    bad[12] ^= 0x55
    dec = StreamDecoder(layout)
    packets = dec.feed(f0 + bytes(bad) + f2)
    assert [p.seq for p in packets] == [0, 2]
    assert dec.stats.crc_errors >= 1
    assert packets[1].gap_before == 1 # seq 1 was lost
    assert dec.stats.packets_lost == 1


def test_sequence_wraparound_is_not_a_gap(layout):
    dec = StreamDecoder(layout)
    packets = dec.feed(layout.encode_frame(NORMAL, seq=65535) + layout.encode_frame(NORMAL, seq=0))
    assert [p.gap_before for p in packets] == [0, 0]


def test_duplicates_dropped_and_out_of_order_counted(layout):
    dec = StreamDecoder(layout)
    f = lambda s: layout.encode_frame(NORMAL, seq=s)
    packets = dec.feed(f(5) + f(5) + f(7) + f(6))
    assert [p.seq for p in packets] == [5, 7, 6]
    assert dec.stats.duplicates == 1
    assert dec.stats.out_of_order == 1
    assert dec.stats.packets_lost == 1