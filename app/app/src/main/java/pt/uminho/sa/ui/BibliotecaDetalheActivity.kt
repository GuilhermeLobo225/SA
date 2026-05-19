package pt.uminho.sa.ui

import android.Manifest
import android.annotation.SuppressLint
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.widget.GridLayout
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.lifecycle.lifecycleScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import pt.uminho.sa.R
import pt.uminho.sa.data.ApiClient
import pt.uminho.sa.data.AssetLoader
import pt.uminho.sa.data.Biblioteca
import pt.uminho.sa.data.Config
import pt.uminho.sa.data.HistoryResponse
import pt.uminho.sa.data.RoomData
import pt.uminho.sa.data.StatBlock
import pt.uminho.sa.data.StatsResponse
import pt.uminho.sa.databinding.ActivityBibliotecaDetalheBinding
import pt.uminho.sa.databinding.ItemSensorTileBinding
import pt.uminho.sa.geofence.GeofenceHandler
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.TimeZone
import kotlin.math.roundToInt

/**
 * Ecrã de detalhe de uma biblioteca.
 *
 * Para a BG (sensorizacao=true) mostra: ocupação ao vivo, planta, sensores,
 * um painel resumo de previsão e botões para registar/remover a geofence.
 *
 * Para as restantes, mostra apenas a ficha e um banner a explicar que ainda
 * não têm sensorização — defendendo a decisão de design: o sistema-piloto
 * só está instalado num nó.
 */
class BibliotecaDetalheActivity : AppCompatActivity() {

    private lateinit var b: ActivityBibliotecaDetalheBinding
    private lateinit var biblioteca: Biblioteca

    /** Job da corrotina de polling. Mantemos a referência para a cancelar em onStop. */
    private var pollingJob: Job? = null

    /** Job do refresh do painel de previsão (cadência mais lenta que o polling). */
    private var previsaoJob: Job? = null

    /** Job do refresh do painel de estatísticas 24h. */
    private var statsJob: Job? = null

    private val geofenceHandler by lazy { GeofenceHandler(this) }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        b = ActivityBibliotecaDetalheBinding.inflate(layoutInflater)
        setContentView(b.root)

        // Toolbar com botão de voltar
        setSupportActionBar(b.toolbar)
        supportActionBar?.setDisplayHomeAsUpEnabled(true)
        b.toolbar.setNavigationOnClickListener { finish() }

        // 1) Identificar a biblioteca pedida
        val id = intent.getStringExtra("biblioteca_id")
        val encontrada = id?.let { AssetLoader.findBiblioteca(this, it) }
        if (encontrada == null) {
            Toast.makeText(this, R.string.erro_carregar, Toast.LENGTH_SHORT).show()
            finish()
            return
        }
        biblioteca = encontrada

        // 2) Preencher tudo o que é estático
        preencherCabecalho()
        preencherInfo()

        // 3) Se tem sensorização, ativar bloco completo + geofencing + polling
        if (biblioteca.sensorizacao) {
            b.sensorBlock.visibility       = View.VISIBLE
            b.geofenceActions.visibility   = View.VISIBLE
            b.btnAbrirHistorico.visibility = View.VISIBLE
            b.previsaoBlock.visibility     = View.VISIBLE
            b.noSensorBanner.visibility    = View.GONE
            configurarPlanta()
            configurarBotoesGeofence()
            configurarBotaoHistorico()
        } else {
            b.sensorBlock.visibility       = View.GONE
            b.geofenceActions.visibility   = View.GONE
            b.btnAbrirHistorico.visibility = View.GONE
            b.previsaoBlock.visibility     = View.GONE
            b.noSensorBanner.visibility    = View.VISIBLE
        }
    }

    override fun onStart() {
        super.onStart()
        // Arranca os polls só quando o ecrã está visível
        if (biblioteca.sensorizacao) {
            iniciarPolling()
            iniciarRefreshPrevisao()
            iniciarRefreshStats()
        }
    }

    override fun onStop() {
        super.onStop()
        // Pára os pollings para não gastar bateria com a app em background
        pollingJob?.cancel(); pollingJob = null
        previsaoJob?.cancel(); previsaoJob = null
        statsJob?.cancel(); statsJob = null
    }

    /* ============================================================
       Cabeçalho e ficha de informações (estáticos)
       ============================================================ */

    private fun preencherCabecalho() {
        b.toolbar.title    = biblioteca.sigla
        b.toolbar.subtitle = biblioteca.campus
        b.eyebrow.text     = "${biblioteca.sigla} · CAMPUS ${biblioteca.campus.uppercase()}"
        b.titulo.text      = biblioteca.nome
        b.descricao.text   = biblioteca.descricao
    }

    private fun preencherInfo() {
        b.infoSigla.text         = label(R.string.label_sigla,    biblioteca.sigla)
        b.infoCampus.text        = label(R.string.label_campus,   "${biblioteca.campus} — ${biblioteca.cidade}")
        b.infoMorada.text        = label(R.string.label_morada,   biblioteca.endereco)
        b.infoTelefone.text      = label(R.string.label_telefone, biblioteca.telefone)
        b.infoEmail.text         = label(R.string.label_email,    biblioteca.email)
        b.infoLugares.text       = label(R.string.label_lugares,  biblioteca.lugares.toString())
        b.infoHorarioLetivo.text = label(R.string.label_horario_letivo, biblioteca.horarioLetivo)
        b.infoHorarioFerias.text = label(R.string.label_horario_ferias, biblioteca.horarioFerias)
    }

    /** Helper: monta "Etiqueta: valor" com a etiqueta em negrito. */
    private fun label(stringRes: Int, valor: String): CharSequence {
        val etiq = getString(stringRes)
        val full = "$etiq: $valor"
        val span = android.text.SpannableString(full)
        span.setSpan(
            android.text.style.StyleSpan(android.graphics.Typeface.BOLD),
            0, etiq.length + 1,
            android.text.Spannable.SPAN_EXCLUSIVE_EXCLUSIVE
        )
        return span
    }

    /* ============================================================
       Planta + descrição do layout
       ============================================================ */

    private fun configurarPlanta() {
        val layout = AssetLoader.loadLayout(this) ?: return
        b.plantaDescricao.text = layout.descricao
        b.planta.setLayout(layout)
    }

    /* ============================================================
       Polling à API (HTTP GET + parse JSON)
       ============================================================ */

    private fun iniciarPolling() {
        pollingJob?.cancel()
        pollingJob = lifecycleScope.launch {
            while (isActive) {
                val roomId = biblioteca.apiRoomId ?: biblioteca.id
                val dados = withContext(Dispatchers.IO) { ApiClient.fetchRoom(roomId) }
                atualizarUI(dados)
                delay(Config.REFRESH_INTERVAL_MS)
            }
        }
    }

    /* ============================================================
       Atualização da UI com os dados ao vivo
       ============================================================ */

    private fun atualizarUI(d: RoomData) {
        // --- Cartão hero ---
        val pct = (d.occupancyPct * 100).roundToInt()
        b.percentagem.text = "$pct%"
        b.estado.text      = estadoEmPortugues(d.status)
        b.lugaresTxt.text  = getString(R.string.lugares_ocupados, d.count, d.capacity)
        b.percentagem.setTextColor(corDoTier(d.occupancyPct))

        // --- Fonte: API vs mock ---
        if (d.source == "api") {
            b.fonteDados.text = "● ${getString(R.string.em_direto)}"
            b.fonteDados.setTextColor(ContextCompat.getColor(this, R.color.status_free))
        } else {
            b.fonteDados.text = "● ${getString(R.string.modo_demo)}"
            b.fonteDados.setTextColor(ContextCompat.getColor(this, R.color.status_unknown))
        }

        // --- Chip LED (estado simplificado lido pelo firmware) ---
        atualizarChipLed(d.statusSimple)

        // --- Última leitura ---
        b.ultimaLeitura.text = getString(R.string.ultima_leitura, formatarHora(d.timestamp))

        // --- Planta: reusa a mesma RoomData ---
        b.planta.setRoomData(d)

        // --- Sensores ---
        atualizarSensores(d)
    }

    /**
     * Recria os mosaicos de sensores a cada update. Para 5 mosaicos isto não
     * tem custo notável e simplifica imenso vs. manter views permanentes.
     *
     * Limiares de alerta alinhados com o README do projeto:
     *  - Temperatura 20–26 °C (ASHRAE 55)
     *  - Humidade 30–70 %
     *  - Qualidade do ar < 800 (ADC bruto 12-bit do MQ-135)
     *  - Iluminância >= 2500 (ADC do fotodíodo) ou DO=0
     *  - Ruído < 55 dB (relativo, MSM261 I2S)
     */
    private fun atualizarSensores(d: RoomData) {
        b.gridSensores.removeAllViews()

        val tempAlerta  = d.temperature?.let { it < 20.0 || it > 26.0 } ?: false
        val humAlerta   = d.humidity?.let { it < 30.0 || it > 70.0 } ?: false
        val arAlerta    = d.airQuality?.let { it > 800 } ?: false
        // Para a iluminância usamos OU o sinal digital (DO=0 → escuro) OU o ADC abaixo do limiar
        val luzAlerta   = (d.lightDigital == 0) || (d.light?.let { it < 2500 } ?: false)
        val ruidoNumAlerta = d.noiseDb?.let { it >= 55.0 } ?: false
        val ruidoTxtAlerta = d.noise == "elevado" || d.noise == "muito_elevado"
        val ruidoAlerta = ruidoNumAlerta || ruidoTxtAlerta

        val tiles = listOf(
            SensorTile(
                icone  = R.drawable.ic_thermometer,
                label  = getString(R.string.sensor_temperatura),
                valor  = d.temperature?.let { String.format(Locale.US, "%.1f °C", it) } ?: "—",
                alerta = tempAlerta
            ),
            SensorTile(
                icone  = R.drawable.ic_info,
                label  = getString(R.string.sensor_humidade),
                valor  = d.humidity?.let { "${it.toInt()} %" } ?: "—",
                alerta = humAlerta
            ),
            SensorTile(
                icone  = R.drawable.ic_info,
                label  = getString(R.string.sensor_qualidade_ar),
                valor  = formatAr(d),
                alerta = arAlerta
            ),
            SensorTile(
                icone  = R.drawable.ic_info,
                label  = getString(R.string.sensor_iluminacao),
                valor  = formatLuz(d),
                alerta = luzAlerta
            ),
            SensorTile(
                icone  = R.drawable.ic_info,
                label  = getString(R.string.sensor_ruido),
                valor  = formatRuido(d),
                alerta = ruidoAlerta
            ),
            // Mosaico "Conforto global" (espelha o tile do website)
            SensorTile(
                icone  = R.drawable.ic_info,
                label  = getString(R.string.sensor_conforto),
                valor  = d.comfort?.let { formatComfort(it) } ?: "—",
                alerta = isBadComfort(d.comfort)
            )
        )

        val inflater = LayoutInflater.from(this)
        for (t in tiles) {
            val tileB = ItemSensorTileBinding.inflate(inflater, b.gridSensores, false)
            tileB.icone.setImageResource(t.icone)
            tileB.label.text = t.label
            tileB.valor.text = t.valor
            if (t.alerta) {
                tileB.root.setBackgroundResource(R.drawable.sensor_tile_bg_alert)
                tileB.valor.setTextColor(ContextCompat.getColor(this, R.color.status_high))
            }
            // Cada mosaico ocupa uma das duas colunas, preenchendo a largura
            val lp = GridLayout.LayoutParams().apply {
                width = 0
                height = GridLayout.LayoutParams.WRAP_CONTENT
                columnSpec = GridLayout.spec(GridLayout.UNDEFINED, 1, 1f)
                setMargins(dp(4), dp(4), dp(4), dp(4))
            }
            b.gridSensores.addView(tileB.root, lp)
        }
    }

    private data class SensorTile(val icone: Int, val label: String, val valor: String, val alerta: Boolean)

    private fun formatAr(d: RoomData): String {
        val n = d.airQuality?.toString() ?: "—"
        val classe = d.airQualityClass?.let { " · ${classeAr(it)}" } ?: ""
        return "$n$classe"
    }

    private fun formatLuz(d: RoomData): String {
        val n = d.light?.toString() ?: "—"
        val flag = if (d.lightDigital == 0) " · escuro" else ""
        return "$n$flag"
    }

    private fun formatRuido(d: RoomData): String {
        val num = d.noiseDb?.let { String.format(Locale.US, "%.1f dB", it) }
        val txt = noiseLabel(d.noise)
        return when {
            num != null && txt != "—" -> "$num · $txt"
            num != null               -> num
            else                       -> txt
        }
    }

    private fun classeAr(s: String): String = when (s) {
        "bom"                  -> "bom"
        "aceitavel"            -> "aceitável"
        "necessita_ventilacao" -> "ventilar"
        "mau"                  -> "mau"
        else                    -> s
    }

    /* ============================================================
       Painel resumo de previsão (próxima hora)
       ============================================================ */

    private fun configurarBotaoHistorico() {
        b.btnAbrirHistorico.setOnClickListener {
            val i = Intent(this, HistoricoActivity::class.java).apply {
                putExtra(HistoricoActivity.EXTRA_ROOM_ID, biblioteca.apiRoomId ?: biblioteca.id)
                putExtra(HistoricoActivity.EXTRA_TITULO, biblioteca.nome)
            }
            startActivity(i)
        }
    }

    private fun iniciarRefreshPrevisao() {
        previsaoJob?.cancel()
        previsaoJob = lifecycleScope.launch {
            while (isActive) {
                refrescarPrevisao()
                delay(PREVISAO_REFRESH_MS)
            }
        }
    }

    /**
     * Vai buscar 3 targets em paralelo (temperatura, ruído, ar) e mostra o
     * valor previsto para ~30 minutos à frente + uma seta de tendência
     * comparando com o último ponto histórico.
     */
    private suspend fun refrescarPrevisao() {
        val roomId = biblioteca.apiRoomId ?: biblioteca.id
        val targets = listOf("temperature", "noise_db", "air_quality")
        val responses = withContext(Dispatchers.IO) {
            targets.map { t -> async { ApiClient.fetchHistory(roomId, t, hours = 2f, forecastMinutes = 60) } }
                .awaitAll()
        }
        // 0: temperatura, 1: ruído, 2: ar
        atualizarItemPrevisao(b.prevTempValor, b.prevTempSeta, responses[0], "°C", 1)
        atualizarItemPrevisao(b.prevRuidoValor, b.prevRuidoSeta, responses[1], "dB", 1)
        atualizarItemPrevisao(b.prevArValor,    b.prevArSeta,    responses[2], "",  0)

        // Fonte (api ou mock)
        val anySource = responses.firstOrNull()?.source ?: "mock"
        b.prevFonte.text = if (anySource == "api")
            getString(R.string.previsao_fonte_api)
        else
            getString(R.string.previsao_fonte_mock)
    }

    private fun atualizarItemPrevisao(
        valorTv: android.widget.TextView,
        setaTv:  android.widget.TextView,
        resp:    HistoryResponse,
        unidade: String,
        decimais: Int
    ) {
        if (!resp.hasForecast) {
            valorTv.text = "—"
            setaTv.text  = ""
            return
        }
        val previsto = resp.forecast.lastOrNull()?.value ?: return
        val atual    = resp.history.lastOrNull()?.value
        val fmt = if (decimais > 0) String.format(Locale.US, "%.${decimais}f", previsto)
                  else              previsto.roundToInt().toString()
        valorTv.text = if (unidade.isNotEmpty()) "$fmt $unidade" else fmt

        if (atual == null) {
            setaTv.text = "→"
            setaTv.setTextColor(ContextCompat.getColor(this, R.color.text_muted))
            return
        }
        val delta = previsto - atual
        val absLimite = 0.5 * (kotlin.math.abs(atual) + 1.0) * 0.02 // 2% relativo, com soft floor
        when {
            kotlin.math.abs(delta) < absLimite -> {
                setaTv.text = "→"
                setaTv.setTextColor(ContextCompat.getColor(this, R.color.text_muted))
            }
            delta > 0 -> {
                setaTv.text = "↗"
                setaTv.setTextColor(ContextCompat.getColor(this, R.color.status_high))
            }
            else -> {
                setaTv.text = "↘"
                setaTv.setTextColor(ContextCompat.getColor(this, R.color.status_free))
            }
        }
    }

    /* ============================================================
       Geofencing
       ============================================================ */

    @SuppressLint("MissingPermission")
    private fun configurarBotoesGeofence() {
        b.btnRegistarGeofence.setOnClickListener {
            if (!temPermissaoLocalizacao()) {
                Toast.makeText(this, R.string.perm_localizacao_msg, Toast.LENGTH_LONG).show()
                return@setOnClickListener
            }
            geofenceHandler.registarGeofenceBG(
                onSuccess = { Toast.makeText(this, R.string.geofence_registada, Toast.LENGTH_SHORT).show() },
                onError   = { msg -> Toast.makeText(this, getString(R.string.geofence_erro, msg), Toast.LENGTH_LONG).show() }
            )
        }
        b.btnRemoverGeofence.setOnClickListener {
            geofenceHandler.removerGeofenceBG {
                Toast.makeText(this, R.string.geofence_removida, Toast.LENGTH_SHORT).show()
            }
        }
    }

    private fun temPermissaoLocalizacao(): Boolean =
        ContextCompat.checkSelfPermission(this, Manifest.permission.ACCESS_FINE_LOCATION) ==
                PackageManager.PERMISSION_GRANTED

    /* ============================================================
       Helpers
       ============================================================ */

    private fun estadoEmPortugues(s: String): String = when (s) {
        "vazio"                -> getString(R.string.estado_vazio)
        "disponivel"           -> getString(R.string.estado_disponivel)
        "parcialmente_ocupado" -> getString(R.string.estado_parcial)
        "quase_cheio"          -> getString(R.string.estado_quase_cheio)
        "cheio"                -> getString(R.string.estado_cheio)
        else                   -> getString(R.string.estado_desconhecido)
    }

    private fun noiseLabel(noise: String?): String = when (noise) {
        "baixo"          -> "Baixo"
        "moderado"       -> "Moderado"
        "elevado"        -> "Elevado"
        "muito_elevado"  -> "Muito elevado"
        null, ""         -> "—"
        else              -> noise
    }

    /** Cor para o texto da percentagem, em função do tier de ocupação. */
    private fun corDoTier(pct: Float): Int = ContextCompat.getColor(this, when {
        pct >= 0.95f -> R.color.status_full
        pct >= 0.75f -> R.color.status_high
        pct >= 0.40f -> R.color.status_mid
        pct >  0f    -> R.color.status_low
        else         -> R.color.status_free
    })

    /**
     * Converte timestamp ISO-8601 (com ou sem 'Z') para "HH:mm:ss" em hora
     * local. O api.py devolve ora ISO sem timezone (do pandas), ora com Z
     * (do isoformat do Python) — toleramos ambos.
     */
    private fun formatarHora(iso: String?): String {
        if (iso.isNullOrEmpty()) return "—"
        val parsers = listOf(
            SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss'Z'", Locale.US).apply { timeZone = TimeZone.getTimeZone("UTC") },
            SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss",    Locale.US).apply { timeZone = TimeZone.getDefault() }
        )
        val out = SimpleDateFormat("HH:mm:ss", Locale.getDefault())
        for (p in parsers) {
            try {
                val d: Date? = p.parse(iso)
                if (d != null) return out.format(d)
            } catch (_: Exception) { /* tentar o próximo */ }
        }
        return iso
    }

    private fun dp(v: Int): Int = (v * resources.displayMetrics.density).toInt()

    /* ============================================================
       Chip LED (estado simplificado livre/parcial/cheio)
       ============================================================ */
    private fun atualizarChipLed(statusSimple: String?) {
        val (txt, bg, fg) = when (statusSimple) {
            "livre"   -> Triple(getString(R.string.led_livre),   R.color.status_free, R.color.text_strong)
            "parcial" -> Triple(getString(R.string.led_parcial), R.color.status_mid,  R.color.text_strong)
            "cheio"   -> Triple(getString(R.string.led_cheio),   R.color.status_full, R.color.text_on_red)
            else      -> Triple("—", R.color.bg_surface, R.color.text_muted)
        }
        b.ledChip.text = "● ${getString(R.string.led_label)} $txt"
        b.ledChip.setBackgroundColor(ContextCompat.getColor(this, bg))
        b.ledChip.setTextColor(ContextCompat.getColor(this, fg))
    }

    /* ============================================================
       Conforto global (mosaico extra alinhado com o website)
       ============================================================ */
    private fun formatComfort(c: String): String = when (c) {
        "bom"      -> "Bom"
        "moderado" -> "Moderado"
        "mau"      -> "Mau"
        else        -> c.replace('_', ' ').replaceFirstChar { it.uppercase() }
    }
    private fun isBadComfort(c: String?): Boolean = c == "mau" || c == "moderado"

    /* ============================================================
       Estatísticas das últimas 24 h
       ============================================================ */
    private fun iniciarRefreshStats() {
        statsJob?.cancel()
        statsJob = lifecycleScope.launch {
            while (isActive) {
                val roomId = biblioteca.apiRoomId ?: biblioteca.id
                val s = withContext(Dispatchers.IO) { ApiClient.fetchStats(roomId, 24) }
                renderStats(s)
                delay(STATS_REFRESH_MS)
            }
        }
    }

    private fun renderStats(s: StatsResponse) {
        val grid = b.gridStats
        grid.removeAllViews()
        val inflater = LayoutInflater.from(this)

        fun fmt(v: Double?, decimais: Int = 1, suffix: String = ""): String {
            if (v == null) return "—"
            val n = if (decimais > 0) String.format(Locale.US, "%.${decimais}f", v)
                    else              v.roundToInt().toString()
            return if (suffix.isEmpty()) n else "$n $suffix"
        }

        val cards = mutableListOf<Triple<Int, String, List<Pair<String, String>>>>()

        // Ocupação (% livre/parcial/cheio + pico)
        s.occupancy?.let { o ->
            cards += Triple(R.drawable.ic_users, getString(R.string.stats_ocupacao), listOf(
                getString(R.string.stats_pct_livre)   to fmt(o.pctLivre,   0, "%"),
                getString(R.string.stats_pct_parcial) to fmt(o.pctParcial, 0, "%"),
                getString(R.string.stats_pct_cheio)   to fmt(o.pctCheio,   0, "%"),
                getString(R.string.stats_pico)        to fmt(o.peak,       0)
            ))
        }
        // Temperatura
        s.temperature?.let { t ->
            cards += Triple(R.drawable.ic_thermometer, getString(R.string.sensor_temperatura),
                blocoRows(t, "°C", 1))
        }
        // Humidade
        s.humidity?.let { h ->
            cards += Triple(R.drawable.ic_info, getString(R.string.sensor_humidade),
                blocoRows(h, "%", 0))
        }
        // Qualidade do ar
        s.airQuality?.let { a ->
            cards += Triple(R.drawable.ic_info, getString(R.string.sensor_qualidade_ar),
                blocoRows(a, "ADC", 0))
        }
        // Ruído
        s.noiseDb?.let { r ->
            cards += Triple(R.drawable.ic_info, getString(R.string.sensor_ruido),
                blocoRows(r, "dB", 1))
        }

        for ((icone, titulo, rows) in cards) {
            val tileB = ItemSensorTileBinding.inflate(inflater, grid, false)
            tileB.icone.setImageResource(icone)
            tileB.label.text = titulo
            // Aproveitamos o TextView do "valor" para empilhar as linhas
            tileB.valor.text = rows.joinToString("\n") { "${it.first}: ${it.second}" }
            tileB.valor.setTextColor(ContextCompat.getColor(this, R.color.text_strong))
            tileB.valor.textSize = 12f
            val lp = GridLayout.LayoutParams().apply {
                width = 0
                height = GridLayout.LayoutParams.WRAP_CONTENT
                columnSpec = GridLayout.spec(GridLayout.UNDEFINED, 1, 1f)
                setMargins(dp(4), dp(4), dp(4), dp(4))
            }
            grid.addView(tileB.root, lp)
        }
    }

    private fun blocoRows(s: StatBlock, unit: String, decimais: Int): List<Pair<String, String>> {
        fun fmt(v: Double?): String {
            if (v == null) return "—"
            val n = if (decimais > 0) String.format(Locale.US, "%.${decimais}f", v)
                    else              v.roundToInt().toString()
            return "$n $unit"
        }
        return listOf(
            getString(R.string.stats_media)   to fmt(s.avg),
            getString(R.string.stats_mediana) to fmt(s.median),
            getString(R.string.stats_maximo)  to fmt(s.max),
            getString(R.string.stats_minimo)  to fmt(s.min)
        )
    }

    companion object {
        /** Refresh do painel de previsão (mais lento que o polling normal). */
        private const val PREVISAO_REFRESH_MS = 60_000L
        /** Refresh do painel de estatísticas 24h (alinhado com o website). */
        private const val STATS_REFRESH_MS = 60_000L
    }
}
