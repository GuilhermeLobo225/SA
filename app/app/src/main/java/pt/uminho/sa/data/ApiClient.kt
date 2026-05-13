package pt.uminho.sa.data

import android.util.Log
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.TimeZone
import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.roundToInt
import kotlin.math.sin

/**
 * Cliente para a API REST do projeto (processing/api.py).
 *
 * Segue exatamente o padrão da PL7:
 *   1. fazer um GET HTTP
 *   2. parse do JSON recebido
 *
 * Usa apenas a biblioteca standard (HttpURLConnection + org.json) — sem
 * Retrofit/Moshi — para minimizar dependências e ficar fiel ao que aprendemos.
 *
 * Se a API não responder (PC desligado), devolve um mock plausível, com a
 * etiqueta source="mock" para a UI poder mostrar "Modo demo · API offline".
 */
object ApiClient {

    private const val TAG = "ApiClient"

    /**
     * GET ${API_BASE}/rooms/${roomId}.
     *
     * Estrutura esperada da resposta:
     * ```
     * {
     *   "room_id": "bg",
     *   "count": 7,
     *   "capacity": 12,
     *   "status": "parcialmente_ocupado",
     *   "comfort": "bom",
     *   "temperature": 22.4,
     *   "humidity": 54,
     *   "air_quality": 320,
     *   "light": 612,
     *   "noise": "baixo",
     *   "timestamp": "2026-05-12T14:32:11Z"
     * }
     * ```
     */
    suspend fun fetchRoom(roomId: String): RoomData = withContext(Dispatchers.IO) {
        try {
            val url = URL("${Config.API_BASE}/rooms/$roomId")
            val conn = (url.openConnection() as HttpURLConnection).apply {
                requestMethod    = "GET"
                connectTimeout   = Config.HTTP_TIMEOUT_MS
                readTimeout      = Config.HTTP_TIMEOUT_MS
                setRequestProperty("Accept", "application/json")
            }

            try {
                if (conn.responseCode != HttpURLConnection.HTTP_OK) {
                    Log.w(TAG, "HTTP ${conn.responseCode} em /rooms/$roomId — a usar mock")
                    return@withContext mockRoom(roomId)
                }
                val body = conn.inputStream.bufferedReader().use { it.readText() }
                return@withContext parseRoomJson(body, roomId)
            } finally {
                conn.disconnect()
            }
        } catch (e: Exception) {
            Log.w(TAG, "API indisponível (${e.javaClass.simpleName}: ${e.message}) — mock")
            return@withContext mockRoom(roomId)
        }
    }

    /* ---------- Parsing ---------- */

    private fun parseRoomJson(body: String, fallbackId: String): RoomData {
        val o = JSONObject(body)
        return RoomData(
            roomId      = o.optString("room_id", fallbackId),
            count       = o.optInt("count", 0),
            capacity    = o.optInt("capacity", 0),
            status      = o.optString("status", "desconhecido"),
            comfort     = o.optString("comfort").ifEmpty { null },
            temperature = if (o.has("temperature") && !o.isNull("temperature")) o.getDouble("temperature") else null,
            humidity    = if (o.has("humidity") && !o.isNull("humidity")) o.getDouble("humidity") else null,
            airQuality  = if (o.has("air_quality") && !o.isNull("air_quality")) o.getInt("air_quality") else null,
            light       = if (o.has("light") && !o.isNull("light")) o.getInt("light") else null,
            noise       = o.optString("noise").ifEmpty { null },
            timestamp   = o.optString("timestamp").ifEmpty { null },
            source      = "api"
        )
    }

    /* ---------- Mock ---------- */

    /**
     * Gera uma RoomData plausível em função do minuto atual, para que a app
     * "funcione" durante a demo mesmo sem a api.py a correr. A variação é
     * suave (sinusoidal) para não dar a sensação de saltos aleatórios.
     */
    private fun mockRoom(roomId: String): RoomData {
        val minute = (System.currentTimeMillis() / 60_000L % 30L).toInt()
        val phase  = minute / 30.0                    // 0 → 1 em meia hora
        val capacity = 12
        val count    = (3 + 8 * sin(phase * PI)).roundToInt().coerceIn(0, capacity)
        val pct      = count.toDouble() / capacity

        val status = when {
            pct >= 0.95 -> "cheio"
            pct >= 0.75 -> "quase_cheio"
            pct >= 0.40 -> "parcialmente_ocupado"
            pct >  0.0  -> "disponivel"
            else        -> "vazio"
        }

        return RoomData(
            roomId      = roomId,
            count       = count,
            capacity    = capacity,
            status      = status,
            comfort     = if (pct > 0.85) "moderado" else "bom",
            temperature = 21.5 + sin(phase * PI * 2) * 1.2,
            humidity    = 52.0 + cos(phase * PI) * 6,
            airQuality  = (290 + phase * 80).roundToInt(),
            light       = (540 + sin(phase * PI) * 90).roundToInt(),
            noise       = if (pct > 0.7) "moderado" else "baixo",
            timestamp   = currentIsoTimestamp(),
            source      = "mock"
        )
    }

    private fun currentIsoTimestamp(): String {
        val sdf = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss'Z'", Locale.US).apply {
            timeZone = TimeZone.getTimeZone("UTC")
        }
        return sdf.format(Date())
    }
}
