package pt.uminho.sa.ui

import android.Manifest
import android.os.Build
import android.os.Bundle
import android.widget.SeekBar
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import android.content.pm.PackageManager
import pt.uminho.sa.R
import pt.uminho.sa.alerts.AlertConfig
import pt.uminho.sa.alerts.AlertPreferences
import pt.uminho.sa.alerts.AlertsScheduler
import pt.uminho.sa.databinding.ActivityAlertasBinding

/**
 * Configuração dos alertas em segundo plano.
 *
 * O utilizador escolhe que tipos de evento o interessam:
 *   - tem lugar (ocupação abaixo de um limiar % escolhido)
 *   - temperatura fora do conforto (20–26 °C)
 *   - ruído elevado
 *
 * Tudo é guardado em SharedPreferences e o `AlertsScheduler` ativa/desativa
 * o `AlertWorker` (WorkManager periódico a cada 15 minutos — mínimo do OS).
 */
class AlertasActivity : AppCompatActivity() {

    private lateinit var b: ActivityAlertasBinding

    private val pedirNotificacoes = registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { /* no-op: o estado é avaliado em onResume */ }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        b = ActivityAlertasBinding.inflate(layoutInflater)
        setContentView(b.root)

        setSupportActionBar(b.toolbar)
        supportActionBar?.setDisplayHomeAsUpEnabled(true)
        b.toolbar.setNavigationOnClickListener { finish() }

        // Estado inicial dos controlos
        val cfg = AlertPreferences.load(this)
        b.switchEnabled.isChecked         = cfg.enabled
        b.switchOcupacao.isChecked         = cfg.occupancyEnabled
        b.sliderLimiar.progress            = cfg.occupancyThresholdPct
        b.switchTemperatura.isChecked      = cfg.temperatureEnabled
        b.switchRuido.isChecked            = cfg.noiseEnabled
        atualizarLabelLimiar(cfg.occupancyThresholdPct)
        atualizarVisibilidadeControlos(cfg.enabled)

        b.switchEnabled.setOnCheckedChangeListener { _, isChecked ->
            atualizarVisibilidadeControlos(isChecked)
            if (isChecked) pedirPermissaoNotificacoesSeNecessario()
        }
        b.switchOcupacao.setOnCheckedChangeListener   { _, _ -> /* só guardamos ao carregar em Guardar */ }
        b.switchTemperatura.setOnCheckedChangeListener { _, _ -> }
        b.switchRuido.setOnCheckedChangeListener      { _, _ -> }

        b.sliderLimiar.setOnSeekBarChangeListener(object : SeekBar.OnSeekBarChangeListener {
            override fun onProgressChanged(s: SeekBar?, progress: Int, fromUser: Boolean) {
                atualizarLabelLimiar(progress)
            }
            override fun onStartTrackingTouch(s: SeekBar?) {}
            override fun onStopTrackingTouch(s: SeekBar?) {}
        })

        b.btnGuardar.setOnClickListener { guardarEAgendar() }
    }

    /* ============================================================
       UI helpers
       ============================================================ */

    private fun atualizarLabelLimiar(progress: Int) {
        b.labelLimiar.text = getString(R.string.alertas_limiar_ocupacao_valor, progress)
    }

    /** Quando o toggle global está off, esmaecemos os controlos para sugerir "desligado". */
    private fun atualizarVisibilidadeControlos(enabled: Boolean) {
        val alpha = if (enabled) 1.0f else 0.45f
        b.grupoRegras.alpha = alpha
        b.switchOcupacao.isEnabled    = enabled
        b.sliderLimiar.isEnabled       = enabled
        b.switchTemperatura.isEnabled  = enabled
        b.switchRuido.isEnabled        = enabled
    }

    private fun pedirPermissaoNotificacoesSeNecessario() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) return
        val granted = ContextCompat.checkSelfPermission(
            this, Manifest.permission.POST_NOTIFICATIONS
        ) == PackageManager.PERMISSION_GRANTED
        if (!granted) pedirNotificacoes.launch(Manifest.permission.POST_NOTIFICATIONS)
    }

    /* ============================================================
       Guardar
       ============================================================ */

    private fun guardarEAgendar() {
        val cfg = AlertConfig(
            enabled              = b.switchEnabled.isChecked,
            occupancyEnabled     = b.switchOcupacao.isChecked,
            occupancyThresholdPct = b.sliderLimiar.progress,
            temperatureEnabled   = b.switchTemperatura.isChecked,
            noiseEnabled         = b.switchRuido.isChecked
        )
        AlertPreferences.save(this, cfg)
        AlertsScheduler.reapply(this, cfg)
        Toast.makeText(this, R.string.alertas_guardados, Toast.LENGTH_SHORT).show()
        finish()
    }
}
