package pt.uminho.sa.ui

import android.content.Context
import android.graphics.Canvas
import android.graphics.Paint
import android.graphics.RectF
import android.util.AttributeSet
import android.view.View
import androidx.core.content.ContextCompat
import pt.uminho.sa.R
import pt.uminho.sa.data.ChairState
import pt.uminho.sa.data.DiscoveredLayout
import kotlin.math.max
import kotlin.math.min

/**
 * Vista da câmara: renderiza o layout descoberto pelo detector na primeira
 * imagem (mesas e cadeiras) e colore cada cadeira em função do estado ao
 * vivo (`ChairState`) vindo da API.
 *
 * Coordenadas:
 *  - O `DiscoveredLayout` traz tudo normalizado em [0..1] relativo à imagem
 *    da câmara. Mantemos o aspect ratio (4:3 por defeito) para que mesas e
 *    cadeiras não fiquem distorcidas quando o tamanho da view varia.
 *  - Cada cadeira é desenhada como um círculo cujo diâmetro acompanha o
 *    menor lado da bounding box (com piso de 28dp para legibilidade).
 *
 * Sem dependências de charting externas — só Canvas e Paint, em linha com
 * o estilo do `PlantaView`.
 */
class CameraView @JvmOverloads constructor(
    context: Context,
    attrs: AttributeSet? = null,
    defStyleAttr: Int = 0
) : View(context, attrs, defStyleAttr) {

    private var layout: DiscoveredLayout? = null
    /** ID da cadeira → estado actual. Reconstruído a cada `setChairStates`. */
    private var statesById: Map<String, ChairState> = emptyMap()

    /* ---------- Pinceis reaproveitados ---------- */
    private val paintBg = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.FILL
        color = android.graphics.Color.parseColor("#FDFBF7")
    }
    private val paintBorder = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeWidth = dp(1.5f)
        color = ContextCompat.getColor(context, R.color.text_strong)
    }
    private val paintGrid = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeWidth = 1f
        color = ContextCompat.getColor(context, R.color.bg_subtle)
    }
    private val paintTable = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeWidth = dp(1.5f)
        color = ContextCompat.getColor(context, R.color.border_strong)
        pathEffect = android.graphics.DashPathEffect(floatArrayOf(dp(6f), dp(4f)), 0f)
    }
    private val paintTableLabel = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        textSize = sp(10f)
        isFakeBoldText = true
        color = ContextCompat.getColor(context, R.color.text_muted)
    }
    private val paintChairFree = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.FILL
        color = android.graphics.Color.parseColor("#59" + "2F8A3E".takeLast(6))   // verde a 35%
    }
    private val paintChairOcc = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.FILL
        color = android.graphics.Color.parseColor("#8C9A1818")    // vermelho a ~55%
    }
    private val paintChairStroke = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeWidth = dp(2f)
        color = ContextCompat.getColor(context, R.color.uminho_red)
    }
    private val paintChairLabel = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        textSize = sp(10f)
        isFakeBoldText = true
        textAlign = Paint.Align.CENTER
        typeface = android.graphics.Typeface.MONOSPACE
        color = ContextCompat.getColor(context, R.color.text_strong)
    }
    private val paintEmpty = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        textSize = sp(11f)
        textAlign = Paint.Align.CENTER
        color = ContextCompat.getColor(context, R.color.text_muted)
    }

    /* ---------- API pública ---------- */

    fun setLayout(l: DiscoveredLayout?) {
        layout = l
        invalidate()
    }

    fun setChairStates(states: List<ChairState>) {
        statesById = states.associateBy { it.id }
        invalidate()
    }

    /* ---------- Desenho ---------- */

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)

        val w = width.toFloat()
        val h = height.toFloat()
        val bgRect = RectF(0.5f, 0.5f, w - 0.5f, h - 0.5f)
        canvas.drawRect(bgRect, paintBg)

        // Grelha decorativa (papel quadriculado)
        val step = dp(20f)
        var x = step
        while (x < w) { canvas.drawLine(x, 0f, x, h, paintGrid); x += step }
        var y = step
        while (y < h) { canvas.drawLine(0f, y, w, y, paintGrid); y += step }

        canvas.drawRect(bgRect, paintBorder)

        val l = layout
        if (l == null || !l.hasData) {
            canvas.drawText(
                context.getString(R.string.camview_empty),
                w / 2f, h / 2f, paintEmpty
            )
            return
        }

        // Mantém o aspect ratio da imagem original para evitar deformações.
        // Se a imagem do detector for, por exemplo, 800x600 e a view for
        // mais larga, centramos a área de plot horizontalmente.
        val imgRatio = if (l.imageWidth > 0 && l.imageHeight > 0)
            l.imageWidth.toFloat() / l.imageHeight else 4f / 3f
        val viewRatio = w / h
        val plotW: Float; val plotH: Float; val offsetX: Float; val offsetY: Float
        if (viewRatio > imgRatio) {
            plotH = h; plotW = h * imgRatio
            offsetX = (w - plotW) / 2f; offsetY = 0f
        } else {
            plotW = w; plotH = w / imgRatio
            offsetX = 0f; offsetY = (h - plotH) / 2f
        }
        fun nx(v: Float) = offsetX + v * plotW
        fun ny(v: Float) = offsetY + v * plotH

        // Mesas como guias tracejadas
        for (t in l.tables) {
            val r = RectF(nx(t.x), ny(t.y), nx(t.x + t.w), ny(t.y + t.h))
            canvas.drawRoundRect(r, dp(3f), dp(3f), paintTable)
            canvas.drawText(t.id, r.left + dp(4f), r.top + paintTableLabel.textSize + dp(2f), paintTableLabel)
        }

        // Cadeiras: círculos coloridos por estado
        for (c in l.chairs) {
            val cx = nx(c.cx)
            val cy = ny(c.cy)
            // Raio: 60% do menor lado da bounding box, com piso de 14dp
            val rawR = 0.5f * min(c.w * plotW, c.h * plotH) * 0.85f
            val r = max(rawR, dp(14f))

            val state = statesById[c.id]
            val occupied = state?.occupied == true
            val fill = if (occupied) paintChairOcc else paintChairFree
            canvas.drawCircle(cx, cy, r, fill)
            canvas.drawCircle(cx, cy, r, paintChairStroke)

            paintChairLabel.color = if (occupied)
                android.graphics.Color.WHITE
            else
                ContextCompat.getColor(context, R.color.text_strong)
            // Centra o texto verticalmente (baseline ≈ textSize * 0.35)
            canvas.drawText(c.id, cx, cy + paintChairLabel.textSize * 0.35f, paintChairLabel)
        }
    }

    /* ---------- Helpers ---------- */
    private fun dp(v: Float): Float = v * resources.displayMetrics.density
    private fun sp(v: Float): Float = v * resources.displayMetrics.scaledDensity
}
