package pt.uminho.sa.ui

import android.Manifest
import android.annotation.SuppressLint
import android.content.pm.PackageManager
import android.graphics.Color
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
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import pt.uminho.sa.R
import pt.uminho.sa.data.ApiClient
import pt.uminho.sa.data.AssetLoader
import pt.uminho.sa.data.Biblioteca
import pt.uminho.sa.data.Config
import pt.uminho.sa.data.RoomData
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
 * Para a BG (sensorizacao=true) mostra: ocupação ao vivo, planta, sensores
 * e botões para registar/remover a geofence (PL8).
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
            b.sensorBlock.visibility    = View.VISIBLE
            b.geofenceActions.visibility = View.VISIBLE
            b.noSensorBanner.visibility = View.GONE
            configurarPlanta()
            configurarBotoesGeofence()
        } else {
            b.sensorBlock.visibility    = View.GONE
            b.geofenceActions.visibility = View.GONE
            b.noSensorBanner.visibility = View.VISIBLE
        }
    }

    override fun onStart() {
        super.onStart()
        // Arranca o polling só quando o ecrã está visível
        if (biblioteca.sensorizacao) iniciarPolling()
    }

    override fun onStop() {
        super.onStop()
        // Pára o polling para não gastar bateria com a app em background
        pollingJob?.cancel()
        pollingJob = null
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
       Polling à API (PL7 — HTTP GET, parse JSON)
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
     */
    private fun atualizarSensores(d: RoomData) {
        b.gridSensores.removeAllViews()

        // Os limiares de "alert" vêm do README do projeto (ASHRAE 55, OMS, EN 12464-1)
        val tiles = listOf(
            SensorTile(R.drawable.ic_thermometer,
                getString(R.string.sensor_temperatura),
                d.temperature?.let { String.format(Locale.US, "%.1f °C", it) } ?: "—",
                alerta = d.temperature?.let { it < 20.0 || it > 26.0 } ?: false),
            SensorTile(R.drawable.ic_info,
                getString(R.string.sensor_humidade),
                d.humidity?.let { "${it.toInt()} %" } ?: "—",
                alerta = d.humidity?.let { it < 30.0 || it > 70.0 } ?: false),
            SensorTile(R.drawable.ic_info,
                getString(R.string.sensor_qualidade_ar),
                d.airQuality?.toString() ?: "—",
                alerta = d.airQuality?.let { it > 400 } ?: false),
            SensorTile(R.drawable.ic_info,
                getString(R.string.sensor_iluminacao),
                d.light?.let { "$it lux" } ?: "—",
                alerta = d.light?.let { it < 500 } ?: false),
            SensorTile(R.drawable.ic_info,
                getString(R.string.sensor_ruido),
                noiseLabel(d.noise),
                alerta = d.noise == "elevado")
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

    /* ============================================================
       Geofencing (PL8)
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
        "baixo"    -> "Baixo"
        "moderado" -> "Moderado"
        "elevado"  -> "Elevado"
        null, ""   -> "—"
        else       -> noise
    }

    /** Cor para o texto da percentagem, em função do tier de ocupação. */
    private fun corDoTier(pct: Float): Int = ContextCompat.getColor(this, when {
        pct >= 0.95f -> R.color.status_full
        pct >= 0.75f -> R.color.status_high
        pct >= 0.40f -> R.color.status_mid
        pct >  0f    -> R.color.status_low
        else         -> R.color.status_free
    })

    /** Converte ISO-8601 (UTC) para "HH:mm:ss" em hora local. */
    private fun formatarHora(iso: String?): String {
        if (iso.isNullOrEmpty()) return "—"
        return try {
            val parser = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss'Z'", Locale.US).apply {
                timeZone = TimeZone.getTimeZone("UTC")
            }
            val out = SimpleDateFormat("HH:mm:ss", Locale.getDefault())
            val date: Date = parser.parse(iso) ?: return iso
            out.format(date)
        } catch (e: Exception) { iso }
    }

    private fun dp(v: Int): Int = (v * resources.displayMetrics.density).toInt()
}
