package pt.uminho.sa.data

import android.content.Context
import org.json.JSONObject
import java.io.BufferedReader
import java.io.InputStreamReader

/**
 * Carrega os dados estáticos da app a partir da pasta assets/.
 *
 * Mantemos as duas fontes em ficheiros pequenos para os ler de forma síncrona —
 * podemos chamar isto a partir de uma corrotina IO sem complicar.
 *
 * O parsing é feito com org.json (built-in Android). Optámos por não usar
 * Gson/Moshi para reduzir dependências.
 */
object AssetLoader {

    private var cachedBibliotecas: List<Biblioteca>? = null
    private var cachedLayout: Layout? = null
    private var cachedLivros: List<Livro>? = null

    /* ============================================================
       BIBLIOTECAS + LAYOUT
       ============================================================ */

    fun loadBibliotecas(context: Context): List<Biblioteca> {
        cachedBibliotecas?.let { return it }
        parseLibrariesJson(context)
        return cachedBibliotecas ?: emptyList()
    }

    fun loadLayout(context: Context): Layout? {
        if (cachedLayout == null) parseLibrariesJson(context)
        return cachedLayout
    }

    fun findBiblioteca(context: Context, id: String): Biblioteca? =
        loadBibliotecas(context).firstOrNull { it.id == id }

    private fun parseLibrariesJson(context: Context) {
        val raw = readAsset(context, "libraries.json")
        val root = JSONObject(raw)

        /* --- Bibliotecas --- */
        val arr = root.getJSONArray("bibliotecas")
        val libs = mutableListOf<Biblioteca>()
        for (i in 0 until arr.length()) {
            val o = arr.getJSONObject(i)
            val horario = o.getJSONObject("horario")
            libs += Biblioteca(
                id           = o.getString("id"),
                nome         = o.getString("nome"),
                sigla        = o.getString("sigla"),
                campus       = o.getString("campus"),
                cidade       = o.getString("cidade"),
                endereco     = o.getString("endereco"),
                telefone     = o.getString("telefone"),
                email        = o.getString("email"),
                horarioLetivo = horario.getString("letivo"),
                horarioFerias = horario.getString("ferias"),
                lugares      = o.getInt("lugares"),
                descricao    = o.getString("descricao"),
                sensorizacao = o.getBoolean("sensorizacao"),
                apiRoomId    = o.optString("api_room_id").takeIf { it.isNotEmpty() }
            )
        }
        cachedBibliotecas = libs

        /* --- Layout da BG --- */
        if (root.has("bg_layout")) {
            val lay = root.getJSONObject("bg_layout")
            val zArr = lay.getJSONArray("zonas")
            val zonas = mutableListOf<Zona>()
            for (i in 0 until zArr.length()) {
                val z = zArr.getJSONObject(i)
                zonas += Zona(
                    id            = z.getString("id"),
                    nome          = z.getString("nome"),
                    lugares       = z.getInt("lugares"),
                    monitorizada  = z.getBoolean("monitorizada"),
                    x             = z.getDouble("x").toFloat(),
                    y             = z.getDouble("y").toFloat(),
                    w             = z.getDouble("w").toFloat(),
                    h             = z.getDouble("h").toFloat(),
                    mesas         = z.getInt("mesas")
                )
            }
            cachedLayout = Layout(
                descricao = lay.getString("descricao"),
                zonas     = zonas
            )
        }
    }

    /* ============================================================
       CATÁLOGO DE LIVROS (books.csv)
       ============================================================
       Parser CSV manual e mínimo — suficiente para um catálogo cujo formato
       controlamos (sem aspas nem vírgulas dentro dos campos).
     */

    fun loadLivros(context: Context): List<Livro> {
        cachedLivros?.let { return it }
        val raw = readAsset(context, "books.csv")
        val lines = raw.lineSequence().filter { it.isNotBlank() }.toList()
        if (lines.isEmpty()) return emptyList()

        val header = lines.first().split(",")
        val idxOf = header.withIndex().associate { (i, name) -> name to i }

        fun col(parts: List<String>, name: String): String =
            idxOf[name]?.let { parts.getOrNull(it) }.orEmpty()

        val list = lines.drop(1).mapNotNull { line ->
            val p = line.split(",")
            if (p.size < header.size) return@mapNotNull null
            Livro(
                id                    = col(p, "id"),
                titulo                = col(p, "titulo"),
                autor                 = col(p, "autor"),
                ano                   = col(p, "ano").toIntOrNull() ?: 0,
                area                  = col(p, "area"),
                bibliotecaId          = col(p, "biblioteca_id"),
                cota                  = col(p, "cota"),
                exemplaresTotal       = col(p, "exemplares_total").toIntOrNull() ?: 0,
                exemplaresDisponiveis = col(p, "exemplares_disponiveis").toIntOrNull() ?: 0
            )
        }
        cachedLivros = list
        return list
    }

    /* ============================================================
       Helper: lê um ficheiro de assets/ inteiro para uma String
       ============================================================ */
    private fun readAsset(context: Context, filename: String): String {
        context.assets.open(filename).use { input ->
            BufferedReader(InputStreamReader(input, Charsets.UTF_8)).use { reader ->
                return reader.readText()
            }
        }
    }
}
