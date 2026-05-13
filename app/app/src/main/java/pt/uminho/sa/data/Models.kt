package pt.uminho.sa.data

/**
 * Classes de dados (POJOs em Kotlin).
 *
 * Mantemos todas as estruturas no mesmo ficheiro porque são pequenas e
 * relacionadas. Não usamos kotlinx-serialization para evitar mais um plugin —
 * o parsing é feito à mão em AssetLoader / ApiClient com org.json (igual ao
 * estilo da PL7 "parse the received JSON").
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
 * Os campos opcionais (null) cobrem o caso em que algum sensor não está a
 * reportar; a UI mostra "—" nesses casos.
 */
data class RoomData(
    val roomId: String,
    val count: Int,
    val capacity: Int,
    val status: String,
    val comfort: String?,
    val temperature: Double?,
    val humidity: Double?,
    val airQuality: Int?,
    val light: Int?,
    val noise: String?,
    val timestamp: String?,
    /** "api" ou "mock" — usado pela UI para mostrar a fonte ao utilizador */
    val source: String
) {
    /** Percentagem de ocupação no intervalo [0f, 1f]. */
    val occupancyPct: Float
        get() = if (capacity > 0) (count.toFloat() / capacity).coerceIn(0f, 1f) else 0f
}
