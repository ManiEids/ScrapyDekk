# Leita Vefskrapa Verkefni

Þetta verkefni er vefskrapa sem safnar saman upplýsingum um dekk frá ýmsum seljendum á Íslandi. Markmiðið er að sameina gögnin á einn stað til að auðvelda samanburð og greiningu.

## Hvernig á að keyra verkefnið

### Undirbúningur

1.  **Hlaða niður og setja upp Python:** Gakktu úr skugga um að Python sé uppsett á tölvunni þinni (útgáfa 3.6 eða nýrri).
2.  **Setja upp Scrapy:** Keyrðu `pip install scrapy` til að setja upp Scrapy.

### Keyra Skrapana

Til að keyra alla skrapana og safna gögnum frá öllum seljendum, keyrðu eftirfarandi skipun:

```bash
# Keyra alla skrapana
python seed.py run_all
```

Þetta mun keyra alla skrapana í verkefninu og vista gögnin í JSON skrár.

### Sameina Gögn frá Seljendum

Til að sameina gögnin úr JSON skrám frá öllum seljendum í eina JSON skrá, keyrðu:

```bash
# Sameina gögn frá öllum seljendum
python merge_tires.py
```

Þetta mun búa til `combined_tire_data.json` skrá með öllum dekkjaupplýsingum.

### Flytja Gögn í Gagnagrunn

Til að flytja sameinuðu gögnin í Neon gagnagrunninn þinn, keyrðu:

```bash
# Flytja gögn í gagnagrunn
python seed.py seed_db
```

Gakktu úr skugga um að þú hafir réttar tengingarupplýsingar fyrir gagnagrunninn þinn í `seed.py` skránni.

## Skipanir

*   `python seed.py run_all`: Keyrir alla vefskrapana og býr til JSON skrár.
*   `python merge_tires.py`: Sameinar allar JSON skrárnar í eina `combined_tire_data.json` skrá.
*   `python seed.py seed_db`: Flytur gögn úr `combined_tire_data.json` í Neon gagnagrunninn.
