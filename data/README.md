# 학습 데이터

`samples/`에는 개인정보가 없는 합성 mmWave 특징 데이터가 들어 있다.
합성 대상 90명에게서 생성한 30초 구간을 사람 단위로 분리한 뒤, 학습 데이터에서 계산한 라벨별 IQR 기준으로 이상치 739행을 제거했다. 최종 데이터는 20,861행이다.

```text
data/
├── docs/labeling-standard.md
├── samples/train.csv
├── samples/validation.csv
├── samples/test.csv
└── generate_synthetic_data.py
```

데이터를 동일하게 다시 만들려면 저장소 루트에서 다음을 실행한다.

```bash
python data/generate_synthetic_data.py
```

이 샘플은 개발 및 데모 전용이며 실제 의료 판단이나 임상 성능 평가에 사용할 수 없다.
