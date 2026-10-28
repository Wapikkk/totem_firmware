# Firmware totem (Raspberry Pi Pico 2 W + MAX98357A)

Pico mendengarkan perintah lewat MQTT (Mosquitto di laptop), mengunduh WAV dari URL di perintah, memutarnya lewat I2S,
dan melaporkan statusnya. Aplikasi/backend berperan sebagai remote.

| File | Isi |
| --- | --- |
| `main.py` | Wi-Fi, MQTT, loop utama, laporan status |
| `player.py` | Unduh WAV, I2S, volume, jeda/lanjut |
| `util.py` | Hal murni tanpa perangkat keras (parse URL/perintah/header WAV), diuji di laptop |
| `config.example.py` | Salin ke `config.py` di Pico dan isi (`config.py` diabaikan git) |

## Kontrak MQTT

Topik memakai `DEVICE_ID` (contoh `totem-001`). Semua pesan JSON UTF-8.

**`talepuff/<id>/cmd`** (aplikasi/backend -> Pico, QoS 1)

| action | Field | Efek |
| --- | --- | --- |
| `play` | `url` (wajib, `http://`), `story_id`, `volume` (0-100, opsional) | Hentikan yang sedang jalan, unduh lalu putar |
| `pause` / `resume` / `stop` | - | Jeda / lanjut / berhenti |
| `volume` | `value` (0-100) | Ubah volume saat memutar |

Volume selalu dipotong ke `MAX_VOLUME` di `config.py` (batas keras di perangkat, di luar batas dari aplikasi).
Pesan yang tidak valid diabaikan dan dicetak di konsol. Jika `ALLOWED_AUDIO_HOST` diisi, URL dari host lain ditolak.

**`talepuff/<id>/status`** (Pico -> aplikasi, retained)

```json
{"state": "playing", "reason": null, "story_id": 7, "position": 12, "duration": 95, "volume": 40}
```

- `state`: `idle`, `loading`, `playing`, `paused`, `error`.
- `reason`: pada `idle` berisi `ended` (selesai sendiri), `stopped`, `wifi_lost`, `connection_lost`;
  pada `error` berisi `unreachable`, `http_404`, `no_response`, `bad_wav`, `stream_lost`.
- `position`/`duration` dalam detik. Posisi dihitung dari data yang sudah dikirim ke I2S, jadi bisa mendahului suara
  sekitar 1 detik (buffer).
- Dikirim saat ada perubahan dan tiap 1 detik selama `playing`.

**`talepuff/<id>/online`** (retained): `1` saat tersambung, `0` otomatis (last will) bila Pico putus.

Perilaku saat Wi-Fi/MQTT putus: pemutaran dihentikan lalu Pico menyambung ulang tiap `RECONNECT_DELAY` detik.

## Mosquitto di laptop (Windows)

1. Pasang Mosquitto. Buat `passwd`: `mosquitto_passwd -c passwd totem-001`, lalu tambahkan pengguna untuk
   backend/aplikasi: `mosquitto_passwd passwd backend`.
2. `mosquitto.conf`:
   ```
   listener 1883 0.0.0.0
   allow_anonymous false
   password_file C:\mosquitto\passwd
   acl_file C:\mosquitto\acl
   ```
3. `acl` (Pico hanya boleh membaca perintahnya sendiri dan menulis statusnya sendiri):
   ```
   user totem-001
   topic read talepuff/totem-001/cmd
   topic write talepuff/totem-001/status
   topic write talepuff/totem-001/online

   user backend
   topic write talepuff/+/cmd
   topic read talepuff/+/status
   topic read talepuff/+/online
   ```
4. Izinkan port 1883 (dan 8000 untuk audio) di Windows Firewall untuk jaringan privat. Pico dan laptop harus satu Wi-Fi
   2,4 GHz.

## Memasang di Pico

1. Di REPL Pico (terhubung internet): `import mip; mip.install("umqtt.simple")`.
2. Salin `config.example.py` menjadi `config.py` dan isi Wi-Fi, IP laptop, dan kata sandi MQTT.
3. Unggah `main.py`, `player.py`, `util.py`, `config.py` ke Pico (Thonny atau `mpremote cp`). Reset; konsol harus
   menampilkan "MQTT tersambung".

## Mencoba tanpa aplikasi

```
cd folder-berisi-wav && python -m http.server 8000
mosquitto_sub -h 127.0.0.1 -u backend -P <sandi> -t "talepuff/totem-001/#" -v
mosquitto_pub -h 127.0.0.1 -u backend -P <sandi> -t talepuff/totem-001/cmd -m "{\"action\":\"play\",\"url\":\"http://IP-LAPTOP:8000/lagu_test.wav\",\"story_id\":1,\"volume\":40}"
mosquitto_pub ... -m "{\"action\":\"pause\"}"
```

Tes logika yang tidak butuh perangkat keras: `python tests/test_util.py`.

## Keterbatasan saat ini

- Hanya `http://`, WAV PCM 16-bit mono/stereo (cocok dengan keluaran layanan AI: mono 24 kHz).
- Saat dijeda, koneksi unduhan tetap terbuka; jeda sangat lama bisa membuat server menutupnya (pemutaran berakhir dengan
  `stream_lost`).
- Tidak ada seek. Audio dari FastAPI masih berupa `http://localhost:8000/...`; URL itu tidak terjangkau Pico, jadi
  backend perlu menyusun URL dengan IP laptop sebelum dikirim (pekerjaan tahap berikutnya).
