# 📱 App Móvel — Sala de Estudo Inteligente

![Kotlin](https://img.shields.io/badge/Android-Kotlin-7F52FF)
![SDK](https://img.shields.io/badge/SDK-34-green)
![Jetpack](https://img.shields.io/badge/Jetpack-WorkManager-blue)
![License](https://img.shields.io/badge/License-Academic-lightgrey)

> Cliente móvel do projeto **Sala de Estudo Inteligente** · Sensorização e Ambiente · MIA · UMinho · 2025/26 · ([README principal](../README.md))

App Android nativa em Kotlin que serve como cliente móvel do projeto **Sala
de Estudo Inteligente**. Espelha a página web do mesmo projeto (lista de
bibliotecas + pesquisa + detalhe da BG) e adiciona duas camadas de
sensorização exclusivas do telemóvel: **geofencing** e **alertas
configuráveis em segundo plano**.

---

## Funcionalidades

| Funcionalidade                                       | Onde está                                              |
|------------------------------------------------------|--------------------------------------------------------|
| Activity + XML + `setOnClickListener`                | `MainActivity.kt`, `BibliotecaDetalheActivity.kt`      |
| ViewBinding (substitui `findViewById`)               | `build.gradle.kts` (`viewBinding = true`)              |
| Pedido HTTP GET                                      | `data/ApiClient.kt` (HttpURLConnection)                |
| Parse JSON (`org.json`)                              | `data/ApiClient.kt`, `data/AssetLoader.kt`             |
| Soft sensor → Firebase no PC, API REST no telemóvel  | arquitetura do projeto                                 |
| Geofencing (`GeofencingClient`)                      | `geofence/GeofenceHandler.kt`                          |
| `BroadcastReceiver` para transições (com `goAsync`)  | `geofence/GeofenceBroadcastReceiver.kt`                |
| Permissões FINE/COARSE/BACKGROUND                    | `AndroidManifest.xml`, `MainActivity.kt`               |
| `PendingIntent` com `FLAG_UPDATE_CURRENT` + `FLAG_MUTABLE` | `GeofenceHandler.kt`                              |
| Custom `View` em Canvas (planta da sala)             | `ui/PlantaView.kt`                                     |
| Custom `View` em Canvas (gráfico de séries temporais)| `ui/HistoryChartView.kt`                               |
| Histórico + previsão a 60 min (cliente da API)       | `ui/HistoricoActivity.kt`, `data/ApiClient.kt#fetchHistory` |
| Painel resumo de previsão no detalhe                 | `ui/BibliotecaDetalheActivity.kt` (`refrescarPrevisao`) |
| Alertas configuráveis em background (`WorkManager`)  | `alerts/AlertWorker.kt`, `alerts/AlertsScheduler.kt`   |
| Preferências do utilizador (`SharedPreferences`)     | `alerts/AlertPreferences.kt`                           |
| Multi-canal de notificações                          | `SaApp.kt` (geofence + alertas configuráveis)          |

---

## Arquitetura em quatro camadas

```
┌──────────── camada UI ──────────────────────────┐
│  MainActivity            BibliotecasAdapter      │
│  CatalogoActivity        LivrosAdapter           │
│  BibliotecaDetalheActivity   PlantaView          │
│  HistoricoActivity           HistoryChartView    │
│  AlertasActivity                                 │
└────────────────┬────────────────────────────────┘
                 │
┌────────────────▼ camada de dados ───────────────┐
│  AssetLoader (libraries.json, books.csv)        │
│  ApiClient   (HTTP GET → api.py)                │
│    ├─ fetchRoom(roomId)                         │
│    └─ fetchHistory(roomId, target, hours, fc)   │
│  Models, Config                                 │
└────────────────┬────────────────────────────────┘
                 │
┌────────────────▼ camada geofence ───────────────┐
│  GeofenceHandler                                 │
│  GeofenceBroadcastReceiver (goAsync + corrotina) │
└────────────────┬────────────────────────────────┘
                 │
┌────────────────▼ camada de alertas ─────────────┐
│  AlertPreferences (SharedPreferences I/O)       │
│  AlertsScheduler  (WorkManager periodic, 15min) │
│  AlertWorker      (CoroutineWorker → API + notif)│
└─────────────────────────────────────────────────┘
```

A app é deliberadamente **simétrica ao site web** (que está em `../website/`):
ambos partilham os mesmos ficheiros de dados estáticos (`libraries.json`,
`books.csv`) e consomem exatamente os mesmos endpoints
(`/api/rooms/{id}`, `/api/rooms/{id}/history`) servidos pela
`processing/api.py`. Isto torna trivial defender que "o pipeline de
dados é único — a camada de apresentação é que multiplica".

---

## Funcionalidades de sensorização

### 1. Detalhe ao vivo (`BibliotecaDetalheActivity`)
Polling a cada 15 s à API, com fallback automático para mock quando o
servidor está offline. Mostra ocupação (% e contagem), planta com
distribuição por mesas, 5 mosaicos de sensores com limiares alinhados ao
README do projeto (ASHRAE 55, EN 12464-1, OMS), e um painel compacto
com a previsão para a próxima hora para temperatura, ruído e qualidade
do ar — incluindo uma seta de tendência (↗/↘/→) comparada com a leitura
atual.

### 2. Histórico e previsão (`HistoricoActivity`)
Gráfico de linhas desenhado em Canvas que mostra simultaneamente o
histórico das últimas 4 horas (linha sólida) e a previsão para os
próximos 60 minutos (linha tracejada). Tem chips para alternar entre
6 métricas (temperatura, humidade, qualidade do ar, iluminância,
ruído, pessoas). A previsão é obtida do mesmo endpoint que o histórico —
no servidor, é produzida pelo `forecast_service.py` (Holt-Winters quando
há dados sazonais suficientes, ou suavização exponencial / naive como
fallbacks).

### 3. Geofencing (`GeofenceBroadcastReceiver`)
Quando o telemóvel entra na zona da BG (raio de 150 m), o sistema dispara
o `BroadcastReceiver`, que usa `goAsync()` para manter o componente vivo
enquanto chama a API e envia uma notificação com a ocupação atual.

### 4. Alertas configuráveis (`AlertasActivity` + `AlertWorker`)
O utilizador escolhe regras no ecrã de Alertas:
* **Tem lugar** — notifica quando a ocupação da BG cai abaixo de um
  limiar em % (configurável via slider).
* **Temperatura fora do conforto** — notifica se a temperatura sair do
  intervalo 20–26 °C.
* **Ruído elevado** — notifica quando `noise == "elevado"`/`"muito_elevado"`
  ou `noise_db >= 55`.

Cada regra ativa o `AlertWorker` (CoroutineWorker) através do
`WorkManager`, que corre a cada 15 minutos (mínimo permitido pelo
Android) sob a restrição de rede disponível. O estado é guardado em
`SharedPreferences` e re-aplicado no `SaApp.onCreate()` para sobreviver
a reboots e kills do processo.

---

## Decisões de design

**Porquê duplicar dados em `assets/`?** Para a app funcionar offline. Os
metadados das bibliotecas e o catálogo de livros nunca mudam em tempo
real — faria pouco sentido bater na rede para os ir buscar.

**Porquê `HttpURLConnection` e não Retrofit?** Para ficar próximo do
standard library do Android e minimizar dependências. Adicionar Retrofit
+ Moshi traria complexidade que não acrescenta valor para uma API com
um punhado de endpoints.

**Porquê fallback mock no `ApiClient`?** Para a demo funcionar mesmo
sem o PC ligado. A UI mostra claramente `● Modo demo · API offline`
quando isto acontece, por honestidade.

**Porquê só a BG mostra ocupação ao vivo?** Porque o sistema-piloto
está instalado apenas num nó. Decisão honesta: melhor mostrar "sem
sensorização" para as outras seis bibliotecas do que inventar números.

**Porquê o `PlantaView` e o `HistoryChartView` são `View`s custom em
vez de usar bibliotecas?** Para manter a app sem dependências de
charting (MPAndroidChart adiciona ~1 MB e mais uma fonte de churn).
Desenhar 5 zonas com Canvas dá ~150 linhas; um gráfico de linhas com
ticks "bonitos" e séries dupla (hist + forecast) dá ~250. Os dois
ficheiros são autoexplicativos e mostram domínio do ciclo
`onMeasure → onDraw`.

**Porquê 15 min no `AlertWorker`?** Porque o Android limita os
`PeriodicWorkRequest` a um mínimo de 15 minutos para proteger a
bateria. Um intervalo mais curto exigiria `AlarmManager` com
`setExactAndAllowWhileIdle`, que requer `SCHEDULE_EXACT_ALARM` em
Android 12+ e tem custo de bateria muito superior.

**Porquê raio de 150 m no geofence?** Abaixo de ~100–150 m o sinal
GPS pode oscilar e dar falsos positivos. Escolhemos o limite inferior
recomendado.

**Porquê pedimos `ACCESS_BACKGROUND_LOCATION` via Definições?** Em
Android 10+ a permissão "Permitir sempre" não pode ser concedida por
runtime dialog — só pelas Definições. A app deteta isto e abre
diretamente a página correta para o utilizador.

---

## Como correr

### Pré-requisitos
- Android Studio Koala (2024.1.1) ou mais recente
- Android SDK 34
- JDK 17

### Passos
1. Abrir o Android Studio em `app/` (ou na raiz `SA/` se quiseres ter o
   projeto inteiro junto)
2. Sync do Gradle (descarrega Gradle 8.7 e todas as dependências,
   incluindo `androidx.work`)
3. Em paralelo, no PC, arrancar a `processing/api.py` (`python api.py`)
4. Correr no emulador (`Run ▶`). A app vai contactar `10.0.2.2:5000`,
   que é o endereço que o emulador usa para chegar ao `localhost` do PC.

### Para correr num telemóvel físico
1. Editar `data/Config.kt` → `API_BASE` para o IP do PC na LAN
   (ex: `http://192.168.1.50:5000/api`)
2. Editar `res/xml/network_security_config.xml` para autorizar esse IP
3. Telemóvel e PC têm de estar na mesma rede Wi-Fi

### Para testar o geofencing
- No detalhe da BG, carregar em "Registar geofence da BG"
- Conceder permissão de localização (Definições → app → Localização → Permitir sempre)
- No emulador: **Extended Controls → Location** → introduzir as coordenadas
  da BG (41.5611, -8.3973). Esperar alguns segundos pela notificação.
- Para testar a saída: mover as coordenadas para longe (ex: lat 41.0)

### Para testar os alertas configuráveis
- Toolbar → ícone do sino → ativar regra "Tem lugar" com limiar 90%
- Como o `PeriodicWorkRequest` arranca o primeiro tick depois do
  intervalo mínimo, para forçar um disparo imediato podes usar o
  Android Studio: **App Inspection → Background Task Inspector →
  selecionar `alerts_worker` → "Run"**.

---

## Estrutura de pastas

```
app/
├── build.gradle.kts                      configuração Gradle (Material 3 + WorkManager)
├── src/main/
│   ├── AndroidManifest.xml               permissões + componentes
│   ├── assets/
│   │   ├── libraries.json                metadados (sincronizado com website/)
│   │   └── books.csv                     catálogo (sincronizado com website/)
│   ├── java/pt/uminho/sa/
│   │   ├── SaApp.kt                      Application — canais + reschedule do worker
│   │   ├── alerts/
│   │   │   ├── AlertPreferences.kt       data class + SharedPreferences
│   │   │   ├── AlertWorker.kt            CoroutineWorker (chama API + dispara notif.)
│   │   │   └── AlertsScheduler.kt        liga/desliga WorkManager periódico
│   │   ├── data/
│   │   │   ├── Config.kt                 constantes
│   │   │   ├── Models.kt                 data classes (room + history + forecast)
│   │   │   ├── AssetLoader.kt            JSON/CSV parser
│   │   │   └── ApiClient.kt              HTTP GET + JSON + mock (fetchRoom + fetchHistory)
│   │   ├── geofence/
│   │   │   ├── GeofenceHandler.kt        registo/remoção de geofences
│   │   │   └── GeofenceBroadcastReceiver.kt   handler com goAsync()
│   │   └── ui/
│   │       ├── MainActivity.kt           lista + ícone "Alertas" na toolbar
│   │       ├── BibliotecaDetalheActivity.kt   detalhe + polling + painel de previsão
│   │       ├── CatalogoActivity.kt       pesquisa de livros
│   │       ├── BibliotecasAdapter.kt
│   │       ├── LivrosAdapter.kt
│   │       ├── PlantaView.kt             Canvas: planta da sala
│   │       ├── HistoryChartView.kt       Canvas: gráfico histórico + previsão
│   │       ├── HistoricoActivity.kt      ecrã de histórico e previsão
│   │       └── AlertasActivity.kt        configuração dos alertas
│   └── res/                              layouts, drawables, menu, strings, cores
└── proguard-rules.pro
```

Autoria: Luís Silva · Pedro Reis · Guilherme Pinto · Pedro Gomes
SVDC/SA · MIA, UMinho · 2025/26
