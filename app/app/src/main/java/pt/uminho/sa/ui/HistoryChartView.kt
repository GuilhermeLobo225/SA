package pt.uminho.sa.ui

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.DashPathEffect
import android.graphics.Paint
import android.graphics.Path
import android.graphics.RectF
import android.util.AttributeSet
import android.view.View
import androidx.core.content.ContextCompat
import pt.uminho.sa.R
import pt.uminho.sa.data.HistoryPoint
import pt.uminho.sa.data.HistoryResponse
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.TimeZone
import kotlin.math.abs
import kotlin.math.floor
import kotlin.math.log10
import kotlin.math.max
import kotlin.math.pow

/**
 * Gráfico de linhas simples para o ecrã de histórico.
 *
 * Duas séries: histórico (linha sólida vermelha + fill subtil) e previsão
 * (linha tracejada azul). O design espelha o gráfico do website, mas é
 * desenhado à mão em Canvas para manter a app sem dependências externas de
 * charting — em linha com o estilo do `PlantaView`.
 *
 * O eixo X é tempo (epoch ms), o eixo Y são os valores numéricos da série.
 * Calculamos automaticamente os ticks (~4 no Y, ~4 no X) para evitar uma
 * dependência num formatador externo.
 */
class HistoryChartView @JvmOverloads constructor(
    context: Context,
    attrs: AttributeSet? = null,
    defStyleAttr: Int = 0
) : View(context, attrs, defStyleAttr) {

    private var resp: HistoryResponse? = null
    private var unidade: String = ""

    /* ---------- Pinceis ---------- */
    private val paintAxis  = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style       = Paint.Style.STROKE
        strokeWidth = dp(1f)
        color       = ContextCompat.getColor(context, R.color.border_soft)
    }
    private val paintGrid  = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style       = Paint.Style.STROKE
        strokeWidth = 1f
        color       = ContextCompat.getColor(context, R.color.border_soft)
        pathEffect  = DashPathEffect(floatArrayOf(4f, 6f), 0f)
    }
    private val paintLabel = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        textSize = sp(11f)
        color    = ContextCompat.getColor(context, R.color.text_muted)
    }
    private val paintHist  = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style       = Paint.Style.STROKE
        strokeWidth = dp(2f)
        color       = ContextCompat.getColor(context, R.color.uminho_red)
    }
    private val paintHistFill = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.FILL
        color = Color.parseColor("#1AA8001F")   // uminho_red @ 10%
    }
    private val paintFc    = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style       = Paint.Style.STROKE
        strokeWidth = dp(2f)
        color       = ContextCompat.getColor(context, R.color.uminho_blue)
        pathEffect  = DashPathEffect(floatArrayOf(dp(6f), dp(4f)), 0f)
    }
    private val paintNowMarker = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style       = Paint.Style.STROKE
        strokeWidth = 1f
        color       = ContextCompat.getColor(context, R.color.text_muted)
        pathEffect  = DashPathEffect(floatArrayOf(2f, 4f), 0f)
    }

    /* ---------- API pública ---------- */

    fun setData(r: HistoryResponse) {
        resp = r
        unidade = r.unit
        invalidate()
    }

    fun clear() {
        resp = null
        invalidate()
    }

    /* ---------- Desenho ---------- */

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)

        val r = resp
        val padL = dp(40f); val padR = dp(8f); val padT = dp(8f); val padB = dp(22f)
        val plotLeft   = padL
        val plotTop    = padT
        val plotRight  = width  - padR
        val plotBottom = height - padB

        // Fundo de plot
        val plotRect = RectF(plotLeft, plotTop, plotRight, plotBottom)
        canvas.drawRect(plotRect, paintAxis)

        if (r == null || (!r.hasData && !r.hasForecast)) {
            paintLabel.color = ContextCompat.getColor(context, R.color.text_muted)
            val msg = if (r == null) "—" else context.getString(R.string.historico_vazio)
            val tw  = paintLabel.measureText(msg)
            canvas.drawText(msg, (width - tw) / 2f, height / 2f, paintLabel)
            return
        }

        // Domínios
        val allPoints = r.history + r.forecast
        val tMin = allPoints.minOf { parseEpoch(it.timestampIso) }
        val tMax = allPoints.maxOf { parseEpoch(it.timestampIso) }
        val tSpan = max(1L, tMax - tMin)

        val rawValues = allPoints.map { it.value.toFloat() }
        var vMin = rawValues.min()
        var vMax = rawValues.max()
        if (abs(vMax - vMin) < 1e-3f) {
            // Série quase plana — abre uma janela artificial para não dividir por 0
            vMin -= 0.5f; vMax += 0.5f
        }
        // Pad ~8% no Y para a linha não tocar nas bordas
        val pad = (vMax - vMin) * 0.08f
        vMin -= pad; vMax += pad

        val plotW = plotRight - plotLeft
        val plotH = plotBottom - plotTop

        fun x(epoch: Long): Float =
            plotLeft + ((epoch - tMin).toFloat() / tSpan.toFloat()) * plotW
        fun y(v: Float): Float =
            plotBottom - ((v - vMin) / (vMax - vMin)) * plotH

        // Ticks Y (~4)
        val yTicks = niceTicks(vMin, vMax, 4)
        for (t in yTicks) {
            val yy = y(t)
            canvas.drawLine(plotLeft, yy, plotRight, yy, paintGrid)
            val lbl = formatYTick(t)
            val tw  = paintLabel.measureText(lbl)
            canvas.drawText(lbl, plotLeft - tw - dp(4f), yy + paintLabel.textSize / 3f, paintLabel)
        }

        // Marca do "agora" (fronteira histórico/previsão) — se houver forecast,
        // o primeiro ponto da forecast é "agora"; senão é o último do histórico.
        val nowEpoch = when {
            r.hasForecast -> parseEpoch(r.forecast.first().timestampIso)
            r.hasData      -> parseEpoch(r.history.last().timestampIso)
            else            -> tMax
        }
        val xNow = x(nowEpoch)
        canvas.drawLine(xNow, plotTop, xNow, plotBottom, paintNowMarker)

        // Ticks X (~4) com hora local
        val xTicks = pickTimeTicks(tMin, tMax, 4)
        for (epoch in xTicks) {
            val xx = x(epoch)
            val lbl = formatTimeTick(epoch)
            val tw  = paintLabel.measureText(lbl)
            canvas.drawText(lbl, xx - tw / 2f, plotBottom + dp(14f), paintLabel)
        }

        // Histórico — linha sólida + área preenchida por baixo
        if (r.hasData) {
            val path = Path()
            val area = Path()
            r.history.forEachIndexed { i, p ->
                val xx = x(parseEpoch(p.timestampIso))
                val yy = y(p.value.toFloat())
                if (i == 0) { path.moveTo(xx, yy); area.moveTo(xx, plotBottom); area.lineTo(xx, yy) }
                else        { path.lineTo(xx, yy); area.lineTo(xx, yy) }
            }
            // Fechar a área de volta ao eixo
            val xLast = x(parseEpoch(r.history.last().timestampIso))
            area.lineTo(xLast, plotBottom)
            area.close()
            canvas.drawPath(area, paintHistFill)
            canvas.drawPath(path, paintHist)
        }

        // Forecast — tracejada. Junta o último ponto do histórico para soldar visualmente.
        if (r.hasForecast) {
            val path = Path()
            val seed = if (r.hasData) r.history.last() else r.forecast.first()
            path.moveTo(x(parseEpoch(seed.timestampIso)), y(seed.value.toFloat()))
            for (p in r.forecast) {
                path.lineTo(x(parseEpoch(p.timestampIso)), y(p.value.toFloat()))
            }
            canvas.drawPath(path, paintFc)
        }
    }

    /* ---------- Helpers de escala / labels ---------- */

    /**
     * Ticks "bonitos" (1, 2, 5 × 10^k). Calcula um passo redondo para o número
     * pretendido de divisões e devolve os múltiplos dentro do intervalo.
     */
    private fun niceTicks(min: Float, max: Float, divs: Int): List<Float> {
        if (max <= min) return listOf(min)
        val raw = (max - min) / divs
        val pow10 = 10.0.pow(floor(log10(raw.toDouble()))).toFloat()
        val frac = raw / pow10
        val nice = when {
            frac < 1.5f -> 1f
            frac < 3f   -> 2f
            frac < 7f   -> 5f
            else        -> 10f
        } * pow10
        val first = (floor((min / nice).toDouble()).toFloat() + 1) * nice
        val out = mutableListOf<Float>()
        var t = first
        while (t < max) {
            out += t
            t += nice
        }
        return out
    }

    private fun pickTimeTicks(tMin: Long, tMax: Long, divs: Int): List<Long> {
        if (divs <= 1) return listOf(tMin, tMax)
        val step = (tMax - tMin) / divs
        return (0..divs).map { tMin + it * step }
    }

    private fun formatYTick(v: Float): String {
        val abs = kotlin.math.abs(v)
        return when {
            abs >= 100f -> v.toInt().toString()
            abs >= 10f  -> String.format(Locale.US, "%.1f", v)
            else         -> String.format(Locale.US, "%.2f", v)
        }
    }

    private val timeFmt = SimpleDateFormat("HH:mm", Locale.getDefault()).apply {
        timeZone = TimeZone.getDefault()
    }
    private fun formatTimeTick(epoch: Long): String = timeFmt.format(Date(epoch))

    /** Parser robusto que aceita ISO com 'Z' (UTC) ou sem timezone (local). */
    private val parsers = listOf(
        SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss'Z'", Locale.US).apply { timeZone = TimeZone.getTimeZone("UTC") },
        SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss",    Locale.US).apply { timeZone = TimeZone.getDefault() }
    )
    private fun parseEpoch(iso: String): Long {
        for (p in parsers) {
            try {
                val d = p.parse(iso)
                if (d != null) return d.time
            } catch (_: Exception) { /* tentar o próximo */ }
        }
        return 0L
    }

    /* ---------- Unidades de UI ---------- */

    private fun dp(v: Float): Float = v * resources.displayMetrics.density
    private fun sp(v: Float): Float = v * resources.displayMetrics.scaledDensity
}
