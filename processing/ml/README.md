# Componente Preditiva (ML)

Treino e avaliação dos modelos de previsão de **conforto ambiental** da Sala de
Estudo Inteligente. Ao contrário do que esta pasta era inicialmente (um
*scaffold* de trabalho futuro), a previsão está agora **integrada no sistema**:
os checkpoints treinados aqui (`models/<target>.pkl`) são carregados em runtime
por [`../forecast_service.py`](../forecast_service.py) e servidos ao website e à
app através do endpoint `GET /api/rooms/<id>/history`.

## Estrutura

```
ml/
├── README.md              ← este ficheiro
├── requirements-ml.txt    ← deps extra (pandas, matplotlib, statsmodels, torch p/ LSTM)
├── forecasting.py         ← compara 3 modelos (Baseline / Holt-Winters / LSTM) e persiste checkpoints
├── data_export.py         ← exporta histórico REAL do Firebase → CSV
├── seed_synthetic.py      ← injeta histórico SINTÉTICO no Firebase
├── seed_csv.py            ← escreve CSV sintético direto (sem Firebase) → data/merged.csv
├── synthetic_models.py    ← modelos de sazonalidade partilhados (occupancy_at, env_at, ...)
├── models/                ← checkpoints treinados: <target>.pkl + <target>.meta.json
└── data/                  ← gerado: CSVs e gráficos (gitignored)
```

Targets persistidos em `models/`: `temperature`, `humidity`, `air_quality_raw`,
`noise_db`.

## Workflow típico

```bash
# 1. Instalar dependências extra
pip install -r ml/requirements-ml.txt

# 2a. Obter dados REAIS do Firebase (quando houver histórico suficiente)
python ml/data_export.py --hours 168            # última semana → data/merged.csv

# 2b. OU gerar dados SINTÉTICOS (recomendado para a demo — ver nota abaixo)
python ml/seed_csv.py --days 14                 # 14 dias → data/merged.csv

# 3. Comparar os 3 modelos numa série
python ml/forecasting.py --target temperature --horizon 1 --plot

# 4. Treinar e persistir os checkpoints que a API usa em produção
python ml/forecasting.py --target all --save    # treina os 4 ambientais → models/
```

Argumentos principais do `forecasting.py`: `--target` (temperature, humidity,
air_quality_raw, noise_db, people, …), `--horizon` (horas de teste no fim da
série), `--plot` / `--plot-report` (gráficos), `--save` (persiste em `models/`;
com `--target all` treina os 4 ambientais), `--data-from` / `--data-to`.

## Integração com a API

`forecast_service.forecast_series(history, minutes_ahead, target)` tenta, por
ordem: (1) o checkpoint Holt-Winters em `models/<target>.pkl`; (2) Holt-Winters
refit online (≥2 dias de histórico); (3) suavização exponencial simples
(≥15 min); (4) *naive* (linha plana). É este serviço que o endpoint `/history`
chama, pelo que basta correr `--target all --save` para que as previsões do
site e da app passem a usar os modelos treinados.

## Resultados (checkpoints atuais)

Métricas guardadas em `models/<target>.meta.json` (modelo Holt-Winters,
*holdout* das últimas 5 h, resample a 5 min):

| Target | MAE | RMSE |
|--------|:---:|:----:|
| temperature (°C) | 0.28 | 0.32 |
| humidity (%) | 1.57 | 1.90 |
| air_quality_raw (ADC) | 557.2 | 602.7 |
| noise_db (dB rel.) | 8.65 | 9.69 |

E (com `--plot`) um gráfico em `data/forecast_<target>.png` com a série real e
as previsões sobrepostas.

## ⚠️ Nota sobre dados sintéticos

O histórico real recolhido cobre apenas ~7 h (a sala esteve maioritariamente
vazia) — insuficiente para Holt-Winters (precisa de ≥2 ciclos diários) ou LSTM
(≥1 semana). Para conseguir **demonstrar e avaliar** a componente preditiva, os
checkpoints atuais foram treinados sobre **14 dias de dados sintéticos** com
sazonalidade realista (`seed_csv.py` / `synthetic_models.py`: ciclo diário de
temperatura, humidade inversa, ar que degrada com a ocupação, padrão
"biblioteca"). Isto está assumido de forma transparente no relatório. Com
semanas de histórico real, basta voltar a correr `data_export.py` +
`forecasting.py --save`.

## Como discutir no relatório

1. **Baseline (média horária)** estabelece o "quanto melhor que adivinhar com
   estatística simples é o nosso modelo?". É o teto mínimo.
2. **Holt-Winters** mostra que muito do sinal está em sazonalidade diária
   (manhã/tarde/noite). Se ganhar pouco vs. baseline → o ambiente é dominado
   por ciclos, não por *shocks*.
3. **LSTM** ganha quando há dependências não-lineares (ex.: temperatura sobe
   mais rápido se a humidade for X e tiver Y pessoas). Se NÃO ganhar → admite-se
   honestamente que para este sinal/volume de dados, o ganho de redes neuronais
   não compensa a complexidade.

## Volume mínimo de dados

| Modelo | Mínimo recomendado |
|---|---|
| Baseline | 1 dia |
| Holt-Winters | 2 dias (precisa de 2 ciclos sazonais) |
| LSTM | 1 semana (idealmente 2+) |

## Âmbito desta entrega

### ✅ No âmbito
- Previsão de **conforto ambiental** (temperatura, humidade, qualidade do ar,
  ruído) — séries suaves e periódicas, treinadas e **servidas ao vivo** pela API.

### ⏭ Trabalho futuro
- **Previsão de ocupação** (`people` / `status`). Tecnicamente trivial reutilizando
  a mesma `forecasting.py` (`--target people`), mas a ocupação é muito mais
  errática e depende de **fatores externos** (horários, exames, época letiva).
  Para um modelo defensável precisaríamos de **semanas a meses** de histórico real.
- Anomaly detection (LSTM autoencoder).
- Multi-target (prever várias séries com uma só rede).
- Integrar inferência em `predictor.py` (loop) + endpoint `predictions/...`
  no Firebase + painel "próximas 2 h" no website.
```

