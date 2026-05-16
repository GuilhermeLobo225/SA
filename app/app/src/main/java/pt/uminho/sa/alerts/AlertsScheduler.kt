package pt.uminho.sa.alerts

import android.content.Context
import androidx.work.Constraints
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.NetworkType
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import java.util.concurrent.TimeUnit

/**
 * Liga/desliga o `AlertWorker` no WorkManager.
 *
 * O WorkManager garante que o trabalho persiste mesmo após reboot, e
 * respeita as restrições de bateria do Doze mode. O intervalo mínimo
 * permitido pelo sistema é 15 minutos — abaixo disso o pedido é silentemente
 * arredondado para cima.
 */
object AlertsScheduler {

    private const val WORK_NAME = "alerts_worker"

    /**
     * Aplica o estado atual dos alertas:
     *   - se enabled E pelo menos uma regra ativa → enfileira o worker periódico
     *   - caso contrário → cancela qualquer trabalho pendente
     *
     * Usar KEEP em vez de REPLACE para não reiniciar o contador a cada save —
     * só refazemos se o trabalho ainda não existir.
     */
    fun apply(context: Context, config: AlertConfig = AlertPreferences.load(context)) {
        val wm = WorkManager.getInstance(context)
        if (!config.enabled || !config.anyRuleActive) {
            wm.cancelUniqueWork(WORK_NAME)
            return
        }
        val request = PeriodicWorkRequestBuilder<AlertWorker>(15, TimeUnit.MINUTES)
            .setConstraints(
                Constraints.Builder()
                    .setRequiredNetworkType(NetworkType.CONNECTED)
                    .build()
            )
            .build()
        wm.enqueueUniquePeriodicWork(WORK_NAME, ExistingPeriodicWorkPolicy.KEEP, request)
    }

    /** Forçar re-enfileirar (ex.: quando o utilizador muda o limiar). */
    fun reapply(context: Context, config: AlertConfig) {
        WorkManager.getInstance(context).cancelUniqueWork(WORK_NAME)
        apply(context, config)
    }
}
