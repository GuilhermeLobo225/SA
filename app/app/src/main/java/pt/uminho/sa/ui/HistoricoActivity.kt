package pt.uminho.sa.ui

import android.os.Bundle
import android.view.View
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.lifecycle.lifecycleScope
import com.google.android.material.chip.Chip
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import pt.uminho.sa.R
import pt.uminho.sa.data.ApiClient
import pt.uminho.sa.data.HistoryResponse
import pt.uminho.sa.databinding.ActivityHistoricoBinding

/**
 * Ecrã de histórico + previsão.
 *
 * Mostra um gráfico de linhas (`HistoryChartView`) com:
 *   - histórico recente (4 h por defeito) — linha sólida
 *   - previsão para os próximos 60 minutos — linha tracejada
 *
 * O utilizador troca de métrica via Chips (temperatura, humidade, ar, luz,
 * ruído, pessoas). Para `people` a API não devolve previsão (trabalho
 * futuro), e indicamo-lo na legenda.
 *
 * Re-fetch automático a cada 60 s — o próprio Firebase só recebe leituras
 * novas a cada 30 s, refresh mais frequente seria desperdício.
 */
class HistoricoActivity : AppCompatActivity() {

    private lateinit var b: ActivityHistoricoBinding
    private lateinit var roomId: String
    private var target: String = "temperature"
    private var refreshJob: Job? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        b = ActivityHistoricoBinding.inflate(layoutInflater)
        setContentView(b.root)

        setSupportActionBar(b.toolbar)
        supportActionBar?.setDisplayHomeAsUpEnabled(true)
        b.toolbar.setNavigationOnClickListener { finish() }

        roomId = intent.getStringExtra(EXTRA_ROOM_ID) ?: "bg"
        val titulo = intent.getStringExtra(EXTRA_TITULO) ?: getString(R.string.title_historico)
        b.toolbar.title = titulo
        b.toolbar.subtitle = getString(R.string.title_historico)

        configurarChips()
    }

    override fun onStart() {
        super.onStart()
        iniciarRefresh()
    }

    override fun onStop() {
        super.onStop()
        refreshJob?.cancel()
        refreshJob = null
    }

    /* ---------- Setup dos chips de métrica ---------- */

    private fun configurarChips() {
        val opcoes = listOf(
            "temperature" to R.string.target_temperature,
            "humidity"    to R.string.target_humidity,
            "air_quality" to R.string.target_air_quality,
            "light"       to R.string.target_light,
            "noise_db"    to R.string.target_noise,
            "people"      to R.string.target_people
        )
        b.chipsTarget.removeAllViews()
        for ((id, label) in opcoes) {
            val chip = Chip(this).apply {
                text       = getString(label)
                isCheckable = true
                isChecked   = id == target
                setOnClickListener {
                    if (target == id) {
                        isChecked = true   // mantém o chip atual ativo se foi re-tocado
                        return@setOnClickListener
                    }
                    target = id
                    // single-select manual: desliga os outros
                    for (i in 0 until b.chipsTarget.childCount) {
                        (b.chipsTarget.getChildAt(i) as? Chip)?.isChecked =
                            (b.chipsTarget.getChildAt(i) === this)
                    }
                    carregar()
                }
            }
            b.chipsTarget.addView(chip)
        }
    }

    /* ---------- Refresh ---------- */

    private fun iniciarRefresh() {
        refreshJob?.cancel()
        refreshJob = lifecycleScope.launch {
            while (isActive) {
                carregar()
                delay(REFRESH_INTERVAL_MS)
            }
        }
    }

    private fun carregar() {
        lifecycleScope.launch {
            b.loading.visibility = View.VISIBLE
            try {
                val resp = withContext(Dispatchers.IO) {
                    ApiClient.fetchHistory(roomId, target, hours = 4f, forecastMinutes = 60)
                }
                aplicar(resp)
            } finally {
                b.loading.visibility = View.GONE
            }
        }
    }

    /* ---------- UI ---------- */

    private fun aplicar(r: HistoryResponse) {
        b.chart.setData(r)

        // Linhas de metadata por baixo do gráfico
        b.metaUnidade.text = getString(R.string.historico_unidade, r.unit.ifEmpty { "—" })
        b.metaModelo.text  = getString(R.string.historico_modelo, modeloLabel(r.model))
        b.metaFonte.text   = if (r.source == "api")
            getString(R.string.em_direto)
        else
            getString(R.string.modo_demo)
        b.metaFonte.setTextColor(
            ContextCompat.getColor(
                this,
                if (r.source == "api") R.color.status_free else R.color.status_unknown
            )
        )

        if (!r.hasData && !r.hasForecast) {
            b.emptyState.visibility = View.VISIBLE
        } else {
            b.emptyState.visibility = View.GONE
        }
    }

    private fun modeloLabel(model: String): String = when (model) {
        "holt-winters"    -> "Holt-Winters (sazonal)"
        "exponential"     -> "Suavização exponencial"
        "naive"           -> "Naive (último valor)"
        "n/a"             -> getString(R.string.previsao_nao_disponivel)
        "mock-sinusoidal" -> getString(R.string.modo_demo)
        ""                -> "—"
        else               -> model
    }

    companion object {
        const val EXTRA_ROOM_ID = "extra_room_id"
        const val EXTRA_TITULO  = "extra_titulo"
        private const val REFRESH_INTERVAL_MS = 60_000L
    }
}
