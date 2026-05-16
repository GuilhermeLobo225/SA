# Componente preditivo (ML)

Estrutura para o trabalho preditivo do projeto. **Não é necessário para o
sistema base funcionar** — esta pasta é puro extra para a parte académica de
"prever conforto / ocupação".

## Estrutura

```
ml/
├── README.md              ← este ficheiro
├── requirements-ml.txt    ← deps extra (pandas, matplotlib, statsmodels)
├── data_export.py         ← exporta histórico do Firebase para CSV
├── forecasting.py         ← compara 3 modelos (baseline / Holt-Winters / LSTM)
└── data/                  ← gerado: CSVs e gráficos (não commitar)
```

## Workflow típico

```bash
# 1. Instalar dependências extra
pip install -r ml/requirements-ml.txt

# 2. Exportar histórico do Firebase para CSV
#    (deixar o sistema a recolher dados durante alguns dias antes deste passo)
python ml/data_export.py --hours 168     # última semana

# 3. Comparar os 3 modelos
python ml/forecasting.py --target temperature --horizon 6 --plot

# Outras targets possíveis: humidity, air_quality_raw, noise_db, people
```

## Resultado esperado

Tabela no stdout do tipo:

```
============================================================
Comparação de previsão  ·  target = temperature
Janela de teste: últimas 6.0 h (360 pontos)
============================================================
Modelo                         MAE      RMSE
------------------------------------------------------------
Baseline (avg por hora)      0.483     0.624
Holt-Winters                 0.298     0.401
LSTM                         0.215     0.298
============================================================
```

E (com `--plot`) um gráfico em `ml/data/forecast_temperature.png` com a série
real e as 3 previsões sobrepostas.

## Como discutir no relatório

1. **Baseline (média horária)** estabelece o "quanto melhor que adivinhar com
   estatística simples é o nosso modelo?". É o teto mínimo.
2. **Holt-Winters** mostra que muito do sinal está em sazonalidade diária
   (manhã/tarde/noite). Se ganhar pouco vs. baseline → o ambiente é dominado
   por ciclos, não por shocks.
3. **LSTM** ganha quando há dependências não-lineares (ex.: temperatura sobe
   mais rápido se a humidade for X e tiver Y pessoas). Se NÃO ganhar → admite
   honestamente que para este sinal/volume de dados, o ganho de redes neuronais
   não compensa a complexidade.

## Volume mínimo de dados

| Modelo | Mínimo recomendado |
|---|---|
| Baseline | 1 dia |
| Holt-Winters | 2 dias (precisa de 2 ciclos sazonais) |
| LSTM | 1 semana (idealmente 2+) |

## Âmbito desta sprint

### ✅ No âmbito (focar aqui)
- Previsão de **conforto ambiental** (temperatura, humidade, qualidade do ar,
  ruído). Estas séries têm dinâmica suave e regular, por isso **algumas
  centenas de horas chegam para mostrar resultado**. O `forecasting.py` cobre
  estas targets.

### ⏭ Trabalho futuro (deixar para outra fase)
- **Previsão de ocupação** (`people` / `status`). Tecnicamente trivial reutilizando
  a mesma `forecasting.py` (`--target people`), mas a ocupação é muito mais
  errática que o ambiente e depende de **fatores externos** (horários, exames,
  época letiva). Para um modelo defensável precisaríamos de **semanas a meses**
  de histórico — fora desta sprint. Justifica-se uma secção "Trabalho futuro"
  no relatório.
- Anomaly detection (LSTM autoencoder).
- Multi-target (prever várias séries com uma só rede).
- Integrar inferência em `predictor.py` (loop) + endpoint `predictions/...`
  no Firebase + painel "próximas 2 h" no website.
