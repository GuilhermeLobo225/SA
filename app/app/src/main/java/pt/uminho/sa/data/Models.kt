package pt.uminho.sa.data

/**
 * Classes de dados (POJOs em Kotlin).
 *
 * Mantemos todas as estruturas no mesmo ficheiro porque são pequenas e
 * relacionadas. Não usamos kotlinx-serialization para evitar mais um plugin —
 * o parsing é feito à mão em AssetLoader / ApiClient com org.json.
 */

/* ---------- Metadados estáticos (vêm de assets/libraries.json) ---------- */

data class Biblioteca(
    val id: String,
    val nome: String,
    val sigla: String,
    val campus: String,
    val cidade: String,
    val endereco: String,
    val telefone: String,
    val email: String,
    val horarioLetivo: String,
    val horarioFerias: String,
    val lugares: Int,
    val descricao: String,
    val sensorizacao: Boolean,
    val apiRoomId: String?
)

data class Zona(
    val id: String,
    val nome: String,
    val lugares: Int,
    val monitorizada: Boolean,
    /** Posição/dimensão normalizada [0..100] usada por PlantaView */
    val x: Float,
    val y: Float,
    val w: Float,
    val h: Float,
    val mesas: Int
)

data class Layout(
    val descricao: String,
    val zonas: List<Zona>
)

/* ---------- Catálogo (vem de assets/books.csv) ---------- */

data class Livro(
    val id: String,
    val titulo: String,
    val autor: String,
    val ano: Int,
    val area: String,
    val bibliotecaId: String,
    val cota: String,
    val exemplaresTotal: Int,
    val exemplaresDisponiveis: Int
)

/* ---------- Dados ao vivo (vêm da api.py ou do mock) ---------- */

/**
 * Resposta de /api/rooms/{id}.
 *
 * Reflete o contrato completo do `build_room_payload` (processing/api.py):
 * ocupação + ambiente, valores numéricos + classes textuais.
 *
 * Os campos opcionais (null) cobrem o caso em que algum sensor não está a
 * reportar; a UI mostra "—" nesses casos.
 */
data class RoomData(
    val roomId: String,
    val timestamp: String?,

    // Ocupação agregada
    val count: Int,
    val capacity: Int,
    val tables: Int,
    val chairsTotal: Int,
    val chairsFree: Int,
    val chairsOccupied: Int,
    /** Percentagem 0..1 vinda da API; em fallback, calculada a partir de count/capacity. */
    val occupancyPctRaw: Float,
    /** 5 níveis (vazio, disponivel, parcialmente_ocupado, quase_cheio, cheio). */
    val status: String,
    /** 3 níveis (livre, parcial, cheio) — usado pelo firmware do LED. */
    val statusSimple: String?,

    // Ambiente — numéricos primários
    val temperature: Double?,
    val humidity: Double?,
    val airQuality: Int?,
    val light: Int?,
    val lightDigital: Int?,
    val noiseDb: Double?,

    // Ambiente — classes textuais
    val comfort: String?,
    val airQualityClass: String?,
    val lightClass: String?,
    val noise: String?,

    /** "api" ou "mock" — usado pela UI para mostrar a fonte ao utilizador */
    val source: String
) {
    /** Percentagem de ocupação no intervalo [0f, 1f]. */
    val occupancyPct: Float
        get() = when {
            occupancyPctRaw > 0f       -> occupancyPctRaw.coerceIn(0f, 1f)
            capacity > 0               -> (count.toFloat() / capacity).coerceIn(0f, 1f)
            else                        -> 0f
        }
}

/* ---------- Histórico + previsão (vêm de /api/rooms/{id}/history) ---------- */

/**
 * Um ponto no tempo de uma série (histórico ou previsão).
 *
 *  - `t` vem em ISO-8601 sem timezone (timestamp local do servidor),
 *    como devolvido por `pd.Timestamp.isoformat(timespec="seconds")`.
 *  - `v` é numérico (unidade depende do target).
 */
data class HistoryPoint(
    val timestampIso: String,
    val value: Double
)

/**
 * Resposta de /api/rooms/{id}/history.
 *
 *   target           — qual a métrica (temperature, humidity, …)
 *   unit             — unidade legível para o eixo Y
 *   model            — modelo usado para a previsão (holt-winters / naive / …)
 *   history          — pontos do histórico recente
 *   forecast         — pontos previstos (pode vir vazio para "people")
 *   source           — "api" se veio da API, "mock" se foi gerado em fallback
 */
data class HistoryResponse(
    val target: String,
    val unit: String,
    val model: String,
    val history: List<HistoryPoint>,
    val forecast: List<HistoryPoint>,
    val source: String
) {
    val hasData: Boolean get() = history.isNotEmpty()
    val hasForecast: Boolean get() = forecast.isNotEmpty()
}
