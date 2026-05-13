package pt.uminho.sa.ui

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.RectF
import android.util.AttributeSet
import android.view.View
import androidx.core.content.ContextCompat
import pt.uminho.sa.R
import pt.uminho.sa.data.Layout
import pt.uminho.sa.data.RoomData
import pt.uminho.sa.data.Zona

/**
 * View customizada que desenha a planta da sala de leitura da BG.
 *
 *  - Cada Zona tem coordenadas normalizadas [0..100], iguais às que o site
 *    usa em SVG. Aqui convertemos para pixéis em onDraw.
 *  - A única zona com sensor (a A) é colorida em função da percentagem de
 *    ocupação reportada pela API; as restantes ficam a cinzento com a
 *    etiqueta "sem sensor".
 *
 * Mantenho-a propositadamente sem dependências externas — só Canvas e Paint —
 * para que se possa explicar linha a linha. Isto cobre material da PL5 sobre
 * Views e UI clássica em Android.
 */
class PlantaView @JvmOverloads constructor(
    context: Context,
    attrs: AttributeSet? = null,
    defStyleAttr: Int = 0
) : View(context, attrs, defStyleAttr) {

    private var layout: Layout?   = null
    private var roomData: RoomData? = null

    /* ---------- Paints reutilizados (alocá-los em onDraw seria mau hábito) ---------- */
    private val paintFill   = Paint(Paint.ANTI_ALIAS_FLAG).apply { style = Paint.Style.FILL }
    private val paintStroke = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeWidth = dp(1.5f)
    }
    private val paintGrid   = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeWidth = 1f
        color = ContextCompat.getColor(context, R.color.bg_subtle)
    }
    private val paintBorder = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeWidth = dp(1.5f)
        color = ContextCompat.getColor(context, R.color.text_strong)
    }
    private val paintTextId = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        textSize = sp(18f)
        isFakeBoldText = true
        color = ContextCompat.getColor(context, R.color.text_strong)
    }
    private val paintTextLabel = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        textSize = sp(9f)
        isFakeBoldText = true
        color = ContextCompat.getColor(context, R.color.text_muted)
    }
    private val paintTextCount = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        textSize = sp(11f)
        typeface = android.graphics.Typeface.MONOSPACE
        isFakeBoldText = true
    }

    /* ---------- API pública ---------- */

    fun setLayout(novo: Layout) {
        layout = novo
        invalidate()
    }

    fun setRoomData(dados: RoomData?) {
        roomData = dados
        invalidate()
    }

    /* ---------- Desenho ---------- */

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        val l = layout ?: return

        // 1. Borda externa da sala
        val rect = RectF(0.5f, 0.5f, width - 0.5f, height - 0.5f)
        paintFill.color = Color.parseColor("#FDFBF7")  // creme claro
        canvas.drawRect(rect, paintFill)
        canvas.drawRect(rect, paintBorder)

        // 2. Grelha decorativa (efeito "papel quadriculado")
        val gridStep = dp(20f)
        var x = gridStep
        while (x < width) {
            canvas.drawLine(x, 0f, x, height.toFloat(), paintGrid)
            x += gridStep
        }
        var y = gridStep
        while (y < height) {
            canvas.drawLine(0f, y, width.toFloat(), y, paintGrid)
            y += gridStep
        }

        // 3. Cada zona
        for (zona in l.zonas) {
            drawZona(canvas, zona)
        }
    }

    private fun drawZona(canvas: Canvas, z: Zona) {
        // Converte percentagens [0..100] em pixéis dentro do view
        val left   = (z.x / 100f) * width
        val top    = (z.y / 100f) * height
        val right  = ((z.x + z.w) / 100f) * width
        val bottom = ((z.y + z.h) / 100f) * height
        val r = RectF(left + dp(2f), top + dp(2f), right - dp(2f), bottom - dp(2f))

        // Cor de fundo: monitorizada -> conforme ocupação; outras -> cinzento
        val (fill, stroke) = corDaZona(z)
        paintFill.color   = fill
        paintStroke.color = stroke
        if (z.monitorizada) paintStroke.strokeWidth = dp(2f) else paintStroke.strokeWidth = dp(1.5f)

        canvas.drawRoundRect(r, dp(3f), dp(3f), paintFill)
        canvas.drawRoundRect(r, dp(3f), dp(3f), paintStroke)

        // Texto: ID grande no canto superior esquerdo + nº de lugares por baixo
        val padding = dp(8f)
        val idColor = if (z.monitorizada) ContextCompat.getColor(context, R.color.uminho_red)
                      else                ContextCompat.getColor(context, R.color.text_strong)
        paintTextId.color = idColor
        canvas.drawText(z.id, r.left + padding, r.top + paintTextId.textSize + dp(2f), paintTextId)
        canvas.drawText("${z.lugares} lug.", r.left + padding,
                        r.top + paintTextId.textSize + paintTextLabel.textSize + dp(4f),
                        paintTextLabel)

        // Para a zona monitorizada (A), mostrar contagem ao vivo no canto inferior direito
        if (z.monitorizada) {
            val d = roomData
            val texto = if (d != null) "${d.count}/${d.capacity}" else "—/${z.lugares}"
            paintTextCount.color = ContextCompat.getColor(context, R.color.text_strong)
            val tw = paintTextCount.measureText(texto)
            canvas.drawText(texto, r.right - padding - tw, r.bottom - padding, paintTextCount)
        } else {
            // Para as outras, escrever "sem sensor" em pequeno
            paintTextLabel.color = ContextCompat.getColor(context, R.color.text_muted)
            val texto = "sem sensor"
            val tw = paintTextLabel.measureText(texto)
            canvas.drawText(texto, r.right - padding - tw, r.bottom - padding, paintTextLabel)
        }
    }

    /**
     * Devolve (cor de preenchimento, cor da borda) para a zona, em função de:
     *  - se é monitorizada (caso contrário: cinzento neutro)
     *  - se há dados ao vivo (e qual a percentagem)
     */
    private fun corDaZona(z: Zona): Pair<Int, Int> {
        if (!z.monitorizada) {
            return Color.parseColor("#26A8A39A") to    // cinzento a 15%
                   ContextCompat.getColor(context, R.color.border_strong)
        }
        val pct = roomData?.occupancyPct ?: 0f
        val fill = when {
            pct >= 0.95f -> Color.parseColor("#529A1818") // muito ocupado: vermelho escuro a 32%
            pct >= 0.75f -> Color.parseColor("#47C44D2F") // alto: laranja-vermelho a 28%
            pct >= 0.40f -> Color.parseColor("#40D6A216") // médio: amarelo a 25%
            pct >  0f    -> Color.parseColor("#404F9E5D") // baixo: verde a 25%
            else         -> Color.parseColor("#262F8A3E") // vazio: verde a 15%
        }
        val stroke = ContextCompat.getColor(context, R.color.uminho_red)
        return fill to stroke
    }

    /* ---------- Helpers ---------- */
    private fun dp(v: Float): Float = v * resources.displayMetrics.density
    private fun sp(v: Float): Float = v * resources.displayMetrics.scaledDensity
}
