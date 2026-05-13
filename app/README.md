# App Móvel — Bibliotecas UMinho

App Android nativa em Kotlin que serve como cliente móvel do projeto **Sala
de Estudo Inteligente**. Espelha a página web do mesmo projeto (lista de
bibliotecas + pesquisa + detalhe da BG) e adiciona uma camada de
sensorização exclusiva do telemóvel: **geofencing**.

---

## Mapa do que está no projeto vs. PLs

| Tema da app                              | Onde está                                | PL  |
|------------------------------------------|------------------------------------------|-----|
| Activity + XML + `setOnClickListener`    | `MainActivity.kt`, `BibliotecaDetalheActivity.kt` | PL5 |
| ViewBinding (substitui `findViewById`)   | `build.gradle.kts` (`viewBinding = true`)| PL5 |
| Pedido HTTP GET                          | `data/ApiClient.kt` (HttpURLConnection)  | PL7 |
| Parse JSON (`org.json`)                  | `data/ApiClient.kt`, `data/AssetLoader.kt`| PL7 |
| Soft sensor → Firebase no PC, API REST no telemóvel | arquitetura do projeto          | PL7 |
| Geofencing (`GeofencingClient`)          | `geofence/GeofenceHandler.kt`            | PL8 |
| `BroadcastReceiver` para transições      | `geofence/GeofenceBroadcastReceiver.kt`  | PL8 |
| Permissões FINE/COARSE/BACKGROUND        | `AndroidManifest.xml`, `MainActivity.kt` | PL8 |
| `PendingIntent` com `FLAG_UPDATE_CURRENT` + `FLAG_MUTABLE` | `GeofenceHandler.kt`    | PL8 |

---

## Arquitetura em três camadas

```
┌──────────── camada UI ────────────┐
│  MainActivity       BibliotecasAdapter │
│  CatalogoActivity   LivrosAdapter      │
│  BibliotecaDetalheActivity  PlantaView │
└────────────────┬──────────────────┘
                 │
┌────────────────▼ camada de dados ─┐
│  AssetLoader (libraries.json, books.csv) │
│  ApiClient   (HTTP GET → api.py)    │
│  Models, Config                     │
└────────────────┬──────────────────┘
                 │
┌────────────────▼ camada geofence ─┐
│  GeofenceHandler                    │
│  GeofenceBroadcastReceiver          │
└─────────────────────────────────────┘
```

A app é deliberadamente **simétrica ao site web** (que está em `../website/`):
ambos partilham os mesmos ficheiros de dados estáticos (`libraries.json`,
`books.csv`) e ambos consomem o mesmo endpoint `GET /api/rooms/bg` da
`processing/api.py`. Isto torna trivial defender que "o pipeline de
dados é único — a camada de apresentação é que multiplica".

---

## Linha de defesa, ponto por ponto

**Porquê duplicar dados em `assets/`?** Para a app funcionar offline. Os
metadados das bibliotecas e o catálogo de livros nunca mudam em tempo real
— faria pouco sentido bater na rede para os ir buscar.

**Porquê `HttpURLConnection` e não Retrofit?** Para ficar próximo do que
vimos em aula (PL7: "make API calls through HTTP Get Requests, parse the
received JSON"). Adicionar Retrofit + Moshi traria complexidade que não
acrescenta valor a um projeto académico com um único endpoint.

**Porquê fallback mock no `ApiClient`?** Para a demo funcionar mesmo sem o
PC ligado. A UI mostra claramente `● Modo demo · API offline` quando isto
acontece, por honestidade.

**Porquê só a BG mostra ocupação ao vivo?** Porque o sistema-piloto está
instalado apenas num nó. Decisão honesta: melhor mostrar "sem
sensorização" para as outras seis bibliotecas do que inventar números.

**Porquê o `PlantaView` é uma `View` custom em vez de XML?** Porque
desenhar 6 retângulos posicionados em percentagens com Canvas dá ~150
linhas; fazer o mesmo com `ConstraintLayout` daria centenas e seria menos
flexível. É também uma boa oportunidade para mostrar domínio do ciclo
`onMeasure → onDraw`.

**Porquê o geofencing?** Material da PL8, mas tornado útil pela junção
com o `ApiClient`: quando o utilizador entra na zona da BG, o
`BroadcastReceiver` faz um GET à API e dispara uma notificação com a
ocupação atual. Aplicação direta de "Vulnerable Road Users are warned as
soon as they enter/exit a geofence" — aqui adaptado a "estudantes
recebem o estado da sala quando passam à porta".

**Porquê raio de 150 m?** A PL8 avisa que abaixo de ~100–150 m o GPS oscila
e causa falsos positivos. Escolhi o limite inferior recomendado.

**Porquê pedimos `ACCESS_BACKGROUND_LOCATION` via Definições?** Como diz a
PL8, em Android 10+ a permissão "Permitir sempre" não pode ser concedida
por runtime dialog — só pelas Definições. A app deteta isto e abre
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
2. Sync do Gradle (descarrega Gradle 8.7 e todas as dependências)
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

---

## Estrutura de pastas

```
app/
├── build.gradle.kts                      configuração Gradle
├── src/main/
│   ├── AndroidManifest.xml               permissões + componentes
│   ├── assets/
│   │   ├── libraries.json                metadados (sincronizado com website/)
│   │   └── books.csv                     catálogo (sincronizado com website/)
│   ├── java/pt/uminho/sa/
│   │   ├── SaApp.kt                      Application — canal de notificações
│   │   ├── data/
│   │   │   ├── Config.kt                 constantes
│   │   │   ├── Models.kt                 data classes
│   │   │   ├── AssetLoader.kt            JSON/CSV parser (PL7 style)
│   │   │   └── ApiClient.kt              HTTP GET + JSON + mock (PL7 style)
│   │   ├── geofence/
│   │   │   ├── GeofenceHandler.kt        (PL8)
│   │   │   └── GeofenceBroadcastReceiver.kt   (PL8)
│   │   └── ui/
│   │       ├── MainActivity.kt           lista
│   │       ├── BibliotecaDetalheActivity.kt   detalhe + polling
│   │       ├── CatalogoActivity.kt       pesquisa de livros
│   │       ├── BibliotecasAdapter.kt
│   │       ├── LivrosAdapter.kt
│   │       └── PlantaView.kt             Canvas custom
│   └── res/                              layouts, drawables, strings, cores
└── proguard-rules.pro
```

Autoria: Luís Silva · Pedro Reis · Guilherme Pinto · Pedro Gomes
SVDC/SA · MIA, UMinho · 2025/26
