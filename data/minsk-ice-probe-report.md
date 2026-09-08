# Minsk ice source probe (spike)

Generated: 2026-09-05T16:29:14+0300

## Summary

- **parse_ready** (times + prices in HTML): **3**
- **times_only**: 4
- **prices_only**: 0
- **reachable_no_signal**: 0
- **unreachable**: 1
- **skipped** (training / not ice): 3

## Per arena

### [3] ТЦ Замок — `parse_ready`
Expectation: mass_skating. Stable hourly grid + prices on same page
- https://tczamok.by/entertainments/ice-rink: status=200, verdict=times_and_prices, times=20, prices=10

### [6] Чижовка-арена — `times_only`
Expectation: mass_skating. Weekly HTML grid; prices on separate page
- https://chizhovka-arena.by/fizkultura-i-sport/katanie-na-konkah: status=200, verdict=times_only, times=17, prices=0

### [5] Ледовый дворец спорта Минской области — `parse_ready`
Expectation: mass_skating. Weekly timetable + pricelist on sibling URL
- http://led.by/category/timetable/: status=200, verdict=times_only, times=20, prices=0
- http://led.by/mass_skating/: status=200, verdict=times_and_prices, times=6, prices=10

### [8] 'Каток хк "Юность"' — `parse_ready`
Expectation: mass_skating. Prices on hockey.by; schedule link may 403
- https://junost.hockey.by/clubs/skating/: status=200, verdict=times_and_prices, times=4, prices=4
- https://junost.by/seansy_massovogo_kataniya_na_vyhodnyh/: status=403, verdict=http_error, times=0, prices=0

### [4] СДЮШОР по фигурному катанию — `unreachable`
Expectation: mass_skating. Weekly grid when not blocked; may return 403
- https://ledlife.by/massovye_kataniya/: status=403, verdict=http_error, times=0, prices=0

### [7] ТЦ DiaMond city — `times_only`
Expectation: mass_skating. Weekly MK grid; prices page may be image/widget
- https://diamondcity.by/ledovaya-arena: status=200, verdict=times_only, times=20, prices=0
- https://diamondcity.by/ceny: status=200, verdict=times_only, times=8, prices=0

### [2] Минск Арена — `times_only`
Expectation: mass_skating. Official widget often stale; ByCard is aggregator
- https://minskarena.by/services.html: status=200, verdict=times_only, times=6, prices=0
- https://bycard.by/afisha/minsk/katki/5821807: status=200, verdict=no_signal, times=0, prices=0

### [9] Олимпик-арена — `times_only`
Expectation: unknown. Corporate site; no public MK schedule found
- https://olympicarena.by/: status=200, verdict=times_only, times=7, prices=0

### [13] 'Хоккейный центр "JUSTSKATE"' — `skip_training_only`
Expectation: training_only. Skating school / rental slots; not municipal MK grid
- https://justskate.by/: status=200, verdict=times_and_prices, times=4, prices=10

### [14] 'Хоккейный центр «Финт»' — `skip_training_only`
Expectation: training_only. Hockey shooting center; phone booking, not MK
- https://fint-tm.by/raspisanie-trenirovok/: status=200, verdict=times_only, times=4, prices=0

### [12] Лыжероллерная трасса — `skip_not_ice`
Expectation: not_ice. Roller/ski track in CRM; skip HTTP probe
