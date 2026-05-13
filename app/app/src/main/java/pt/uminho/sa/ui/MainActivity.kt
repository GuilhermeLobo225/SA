package pt.uminho.sa.ui

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.util.Log
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.lifecycle.lifecycleScope
import androidx.recyclerview.widget.LinearLayoutManager
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import pt.uminho.sa.R
import pt.uminho.sa.data.AssetLoader
import pt.uminho.sa.databinding.ActivityMainBinding

/**
 * Ecrã inicial: lista de bibliotecas.
 *
 * Responsabilidades:
 *  - Carrega as bibliotecas em background a partir de assets/libraries.json
 *  - Mostra-as numa RecyclerView; tocar num cartão abre a Activity de detalhe
 *  - FAB no canto inferior abre a CatalogoActivity (pesquisa de livros)
 *  - Pede permissões de localização (necessárias para registar a geofence
 *    da BG no detalhe — PL8). As permissões são pedidas aqui, no arranque,
 *    para que quando o utilizador for ao detalhe já estejam tratadas.
 */
class MainActivity : AppCompatActivity() {

    private lateinit var b: ActivityMainBinding
    private lateinit var adapter: BibliotecasAdapter

    /* ---------- Launchers de permissões (API moderno: ActivityResult) ---------- */

    private val pedirFineLocation = registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { concedida ->
        if (concedida) {
            // Em API 29+ ainda falta pedir background, e isso só funciona
            // via Definições do sistema (não através de runtime dialog).
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q && !temBackgroundLocation()) {
                mostrarDialogoBackgroundLocation()
            }
        }
    }

    private val pedirNotificacoes = registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { /* sem-op: a notificação só é necessária quando o geofence dispara */ }

    /* ---------- Ciclo de vida ---------- */

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        b = ActivityMainBinding.inflate(layoutInflater)
        setContentView(b.root)

        setSupportActionBar(b.toolbar)

        configurarLista()
        configurarFab()
        configurarPullToRefresh()

        carregarBibliotecas()
        pedirPermissoesIniciais()
    }

    /* ---------- UI setup ---------- */

    private fun configurarLista() {
        adapter = BibliotecasAdapter(emptyList()) { biblio ->
            // Tap num cartão -> abre o detalhe
            val intent = Intent(this, BibliotecaDetalheActivity::class.java).apply {
                putExtra("biblioteca_id", biblio.id)
            }
            startActivity(intent)
        }
        b.listaBibliotecas.layoutManager = LinearLayoutManager(this)
        b.listaBibliotecas.adapter       = adapter
    }

    private fun configurarFab() {
        b.fabCatalogo.setOnClickListener {
            startActivity(Intent(this, CatalogoActivity::class.java))
        }
    }

    private fun configurarPullToRefresh() {
        b.swipeRefresh.setColorSchemeResources(R.color.uminho_red, R.color.uminho_blue)
        b.swipeRefresh.setOnRefreshListener { carregarBibliotecas() }
    }

    /* ---------- Carregamento dos dados ---------- */

    private fun carregarBibliotecas() {
        // A leitura do JSON dos assets é rápida mas faz-se em IO por boa prática
        lifecycleScope.launch {
            b.loading.visibility = android.view.View.VISIBLE
            try {
                val lista = withContext(Dispatchers.IO) { AssetLoader.loadBibliotecas(this@MainActivity) }
                adapter.submit(lista)
            } catch (e: Exception) {
                Log.e(TAG, "Falhou a carregar bibliotecas", e)
            } finally {
                b.loading.visibility = android.view.View.GONE
                b.swipeRefresh.isRefreshing = false
            }
        }
    }

    /* ---------- Permissões ---------- */

    private fun pedirPermissoesIniciais() {
        // 1. Localização precisa (FINE) — pré-requisito do geofencing
        if (!temFineLocation()) {
            pedirFineLocation.launch(Manifest.permission.ACCESS_FINE_LOCATION)
        }
        // 2. Notificações (Android 13+) — sem isto o geofence dispara mas o utilizador não vê nada
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU && !temNotificacoes()) {
            pedirNotificacoes.launch(Manifest.permission.POST_NOTIFICATIONS)
        }
    }

    private fun temFineLocation(): Boolean = ContextCompat.checkSelfPermission(
        this, Manifest.permission.ACCESS_FINE_LOCATION
    ) == PackageManager.PERMISSION_GRANTED

    private fun temBackgroundLocation(): Boolean {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.Q) return true
        return ContextCompat.checkSelfPermission(
            this, Manifest.permission.ACCESS_BACKGROUND_LOCATION
        ) == PackageManager.PERMISSION_GRANTED
    }

    private fun temNotificacoes(): Boolean {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) return true
        return ContextCompat.checkSelfPermission(
            this, Manifest.permission.POST_NOTIFICATIONS
        ) == PackageManager.PERMISSION_GRANTED
    }

    /**
     * Em Android 10+, a permissão "Permitir sempre" só pode ser concedida nas
     * Definições — exatamente como avisa a PL8. O sistema não permite que
     * peçamos por runtime dialog. Daí esta caixa que reencaminha o utilizador.
     */
    private fun mostrarDialogoBackgroundLocation() {
        AlertDialog.Builder(this)
            .setTitle(R.string.perm_localizacao_titulo)
            .setMessage(R.string.perm_localizacao_msg)
            .setPositiveButton(R.string.perm_abrir_definicoes) { _, _ ->
                val intent = Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS).apply {
                    data = Uri.fromParts("package", packageName, null)
                }
                startActivity(intent)
            }
            .setNegativeButton(R.string.cancelar, null)
            .show()
    }

    companion object { private const val TAG = "MainActivity" }
}
