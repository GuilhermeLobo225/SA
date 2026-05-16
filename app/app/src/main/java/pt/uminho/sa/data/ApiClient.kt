package pt.uminho.sa.data

import android.util.Log
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder
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
 * Padrão:
 *   1. fazer um GET HTTP
 *   2. parse do JSON recebido
 *
 * Usa apenas a biblioteca standard (HttpURLConnection + org.json) — sem
 * Retrofit/Moshi — para minimizar dependências.
 *
 * Se a API não responder (PC desligado), devolve um mock plausível, com a
 * etiqueta source="mock" para a UI poder mostrar "Modo demo · API offline".
 */
object ApiClient {

    private const val TAG = "ApiClient"

    /* ============================================================
       GET /api/rooms/{roomId}
       ============================================================ */

    suspend fun fetchRoom(roomId: String): RoomData = withContext(Dispatchers.IO) {
        val url = "${Config.API_BASE}/rooms/$roomId"
        val body = doGet(url) ?: return@withContext mockRoom(roomId)
        return@withContext try {
            parseRoomJson(body, roomId)
        } catch (e: Exception) {
            Log.w(TAG, "Falhou parse de /rooms/$roomId (${e.javaClass.simpleName}: ${e.message})", e)
            mockRoom(roomId)
        }
    }

    /* ============================================================
       GET /api/rooms/{roomId}/history?target=…&hours=…&forecast_minutes=…
       ============================================================ */

    suspend fun fetchHistory(
        roomId: String,
        target: String,
        hours: Float = 4f,
        forecastMinutes: Int = 60
    ): HistoryResponse = withContext(Dispatchers.IO) {
        val q = listOf(
            "target=${enc(target)}",
            "hours=${hours}",
            "forecast_minutes=${forecastMinutes}"
        ).joinToString("&")
        val url = "${Config.API_BASE}/rooms/$roomId/history?$q"

        val body = doGet(url) ?: return@withContext mockHistory(target)
        return@withContext try {
            parseHistoryJson(body)
        } catch (e: Exception) {
            Log.w(TAG, "Falhou parse de /history (${e.javaClass.simpleName}: ${e.message})", e)
            mockHistory(target)
        }
    }

    /* ============================================================
       HTTP plumbing
       ============================================================ */

    private fun doGet(url: String): String? {
        return try {
            val conn = (URL(url).openConnection() as HttpURLConnection).apply {
                requestMethod    = "GET"
                connectTimeout   = Config.HTTP_TIMEOUT_MS
                readTimeout      = Config.HTTP_TIMEOUT_MS
                setRequestProperty("Accept", "application/json")
            }
            try {
                if (conn.responseCode != HttpURLConnection.HTTP_OK) {
                    Log.w(TAG, "HTTP ${conn.responseCode} em $url")
                    return null
                }
                conn.inputStream.bufferedReader().use { it.readText() }
            } finally {
                conn.disconnect()
            }
        } catch (e: Exception) {
            Log.w(TAG, "API indisponível em $url (${e.javaClass.simpleName}: ${e.message})")
            null
        }
    }

    private fun enc(s: String): String = URLEncoder.encode(s, "UTF-8")

    /* ============================================================
       Parsing
       ============================================================ */

    private fun parseRoomJson(body: String, fallbackId: String): RoomData {
        val o = JSONObject(body)
        return RoomData(
            roomId          = o.optString("room_id", fallbackId),
            timestamp       = o.optString("timestamp").ifEmpty { null },

            count           = o.optInt("count", o.optInt("people", 0)),
            capacity        = o.optInt("capacity", 0),
            tables          = o.optInt("tables", 0),
            chairsTotal     = o.optInt("chairs_total", 0),
            chairsFree      = o.optInt("chairs_free", 0),
            occupancyPctRaw = optFloat(o, "occupancy_pct"),
            status          = o.optString("status", "desconhecido"),
            statusSimple    = o.optString("status_simple").ifEmpty { null },

            temperature     = optDouble(o, "temperature"),
            humidity        = optDouble(o, "humidity"),
            airQuality      = optInt(o, "air_quality"),
            light           = optInt(o, "light"),
            lightDigital    = optInt(o, "light_digital"),
            noiseDb         = optDouble(o, "noise_db"),

            comfort         = o.optString("comfort").ifEmpty { null },
            airQualityClass = o.optString("air_quality_class").ifEmpty { null },
            lightClass      = o.optString("light_class").ifEmpty { null },
            noise           = o.optString("noise").ifEmpty { null },

            source          = "api"
        )
    }

    private fun parseHistoryJson(body: String): HistoryResponse {
        val o = JSONObject(body)
        val histArr = o.optJSONArray("history")
        val fcArr   = o.optJSONArray("forecast")
        val history = mutableListOf<HistoryPoint>()
        val forecast = mutableListOf<HistoryPoint>()
        if (histArr != null) {
            for (i in 0 until histArr.length()) {
                val p = histArr.getJSONObject(i)
                history += HistoryPoint(
                    timestampIso = p.optString("t"),
                    value        = p.optDouble("v")
                )
            }
        }
        if (fcArr != null) {
            for (i in 0 until fcArr.length()) {
                val p = fcArr.getJSONObject(i)
                forecast += HistoryPoint(
                    timestampIso = p.optString("t"),
                    value        = p.optDouble("v")
                )
            }
        }
        return HistoryResponse(
            target   = o.optString("target"),
            unit     = o.optString("unit"),
            model    = o.optString("model").ifEmpty { "naive" },
            history  = history,
            forecast = forecast,
            source   = "api"
        )
    }

    /* Helpers para campos opcionais que podem vir null no JSON. */
    private fun optDouble(o: JSONObject, key: String): Double? =
        if (o.has(key) && !o.isNull(key)) o.optDouble(key).takeIf { !it.isNaN() } else null

    private fun optFloat(o: JSONObject, key: String): Float =
        optDouble(o, key)?.toFloat() ?: 0f

    private fun optInt(o: JSONObject, key: String): Int? =
        if (o.has(key) && !o.isNull(key)) o.optInt(key) else null

    /* ============================================================
       Mocks (quando a API está offline)
       ============================================================ */

    /**
     * Gera uma RoomData plausível em função do minuto atual, para que a app
     * "funcione" durante a demo mesmo sem a api.py a correr. A variação é
     * suave (sinusoidal) para não dar a sensação de saltos aleatórios.
     */
    private fun mockRoom(roomId: String): RoomData {
        val minute = (System.currentTimeMillis() / 60_000L % 30L).toInt()
        val phase  = minute / 30.0                    // 0 → 1 em meia hora
        val capacity = 8
        val count    = (3 + 4 * sin(phase * PI)).roundToInt().coerceIn(0, capacity)
        val pct      = count.toDouble() / capacity

        val status = when {
            pct >= 0.95 -> "cheio"
            pct >= 0.75 -> "quase_cheio"
            pct >= 0.40 -> "parcialmente_ocupado"
            pct >  0.0  -> "disponivel"
            else        -> "vazio"
        }
        val statusSimple = when {
            pct >= 0.95 -> "cheio"
            pct >  0.0  -> "parcial"
            else        -> "livre"
        }

        return RoomData(
            roomId          = roomId,
            timestamp       = currentIsoTimestamp(),

            count           = count,
            capacity        = capacity,
            tables          = 2,
            chairsTotal     = capacity,
            chairsFree      = capacity - count,
            occupancyPctRaw = pct.toFloat(),
            status          = status,
            statusSimple    = statusSimple,

            temperature     = 21.5 + sin(phase * PI * 2) * 1.2,
            humidity        = 52.0 + cos(phase * PI) * 6,
            airQuality      = (290 + phase * 80).roundToInt(),
            light           = (1800 + sin(phase * PI) * 400).roundToInt(),
            lightDigital    = 0,
            noiseDb         = 32.0 + sin(phase * PI) * 8.0,

            comfort         = if (pct > 0.85) "moderado" else "bom",
            airQualityClass = "aceitavel",
            lightClass      = "adequado",
            noise           = if (pct > 0.7) "moderado" else "baixo",

            source          = "mock"
        )
    }

    /** Histórico mock — sinusoidal nas últimas 4 horas, com uma "previsão" para a hora seguinte. */
    private fun mockHistory(target: String): HistoryResponse {
        val now = System.currentTimeMillis()
        val (unit, baseline, amplitude) = when (target) {
            "temperature" -> Triple("°C",       22.0, 1.5)
            "humidity"    -> Triple("%",        52.0, 5.0)
            "air_quality" -> Triple("ADC",     320.0, 60.0)
            "light"       -> Triple("ADC",    1800.0, 350.0)
            "noise_db"    -> Triple("dB rel.",  34.0, 6.0)
            "people"      -> Triple("pessoas",   4.0, 3.0)
            else          -> Triple("",          0.0, 1.0)
        }

        val history = mutableListOf<HistoryPoint>()
        // 4 horas × 12 pontos/hora = 48 pontos (a cada 5 minutos)
        for (i in 0 until 48) {
            val tMillis = now - (48 - i) * 5 * 60_000L
            val phase = i / 12.0   // dois ciclos completos em 4h
            val v = baseline + amplitude * sin(phase * PI)
            history += HistoryPoint(
                timestampIso = isoLocal(tMillis),
                value        = if (target == "people") v.roundToInt().toDouble() else v
            )
        }
        val forecast = if (target == "people") emptyList() else mutableListOf<HistoryPoint>().also { out ->
            for (i in 1..12) {
                val tMillis = now + i * 5 * 60_000L
                val phase = (48 + i) / 12.0
                val v = baseline + amplitude * sin(phase * PI)
                out += HistoryPoint(isoLocal(tMillis), v)
            }
        }
        return HistoryResponse(
            target   = target,
            unit     = unit,
            model    = if (target == "people") "n/a" else "mock-sinusoidal",
            history  = history,
            forecast = forecast,
            source   = "mock"
        )
    }

    /* ============================================================
       Timestamps
       ============================================================ */

    private fun currentIsoTimestamp(): String {
        val sdf = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss'Z'", Locale.US).apply {
            timeZone = TimeZone.getTimeZone("UTC")
        }
        return sdf.format(Date())
    }

    /** Formato local sem timezone — espelha o `pd.Timestamp.isoformat` do servidor. */
    private fun isoLocal(millis: Long): String {
        val sdf = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss", Locale.US)
        sdf.timeZone = TimeZone.getDefault()
        return sdf.format(Date(millis))
    }
}
