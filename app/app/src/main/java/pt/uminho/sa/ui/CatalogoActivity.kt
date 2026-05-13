package pt.uminho.sa.ui

import android.os.Bundle
import android.text.Editable
import android.text.TextWatcher
import android.view.View
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import androidx.recyclerview.widget.DividerItemDecoration
import androidx.recyclerview.widget.LinearLayoutManager
import com.google.android.material.chip.Chip
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import pt.uminho.sa.R
import pt.uminho.sa.data.AssetLoader
import pt.uminho.sa.data.Livro
import pt.uminho.sa.databinding.ActivityCatalogoBinding

/**
 * Ecrã de pesquisa do catálogo de livros.
 *
 * O catálogo é pequeno (~80 livros) e está bundled em assets/books.csv, por
 * isso a pesquisa é feita inteiramente client-side: cada keystroke filtra a
 * lista completa em memória. Não vale a pena introduzir Room nem rede aqui.
 *
 * Os filtros por área são chips Material; só pode estar um ativo de cada vez
 * (single-select). O chip "Todas as áreas" funciona como reset.
 */
class CatalogoActivity : AppCompatActivity() {

    private lateinit var b: ActivityCatalogoBinding
    private lateinit var adapter: LivrosAdapter

    /** Lista completa carregada uma vez no arranque; nunca é alterada. */
    private var todos: List<Livro> = emptyList()

    /** Estado atual dos filtros. */
    private var query: String = ""
    private var areaSelecionada: String = ""

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        b = ActivityCatalogoBinding.inflate(layoutInflater)
        setContentView(b.root)

        setSupportActionBar(b.toolbar)
        supportActionBar?.setDisplayHomeAsUpEnabled(true)
        b.toolbar.setNavigationOnClickListener { finish() }

        configurarLista()
        configurarPesquisa()
        carregarCatalogo()
    }

    /* ---------- Setup ---------- */

    private fun configurarLista() {
        adapter = LivrosAdapter(emptyList(), emptyMap())
        b.listaLivros.layoutManager = LinearLayoutManager(this)
        b.listaLivros.adapter       = adapter
        // Separador subtil entre linhas
        b.listaLivros.addItemDecoration(DividerItemDecoration(this, DividerItemDecoration.VERTICAL))
    }

    private fun configurarPesquisa() {
        b.searchInput.addTextChangedListener(object : TextWatcher {
            override fun afterTextChanged(s: Editable?) {
                query = s?.toString()?.trim()?.lowercase().orEmpty()
                aplicarFiltros()
            }
            override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
            override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {}
        })
    }

    /* ---------- Carregamento ---------- */

    private fun carregarCatalogo() {
        lifecycleScope.launch {
            val (livros, bibliotecas) = withContext(Dispatchers.IO) {
                val l = AssetLoader.loadLivros(this@CatalogoActivity)
                val b = AssetLoader.loadBibliotecas(this@CatalogoActivity)
                l to b
            }
            todos = livros
            // Adapter precisa do mapa id→sigla das bibliotecas para a meta
            adapter = LivrosAdapter(emptyList(), LivrosAdapter.mapearSiglas(bibliotecas))
            b.listaLivros.adapter = adapter

            criarChipsDeArea()
            aplicarFiltros()
        }
    }

    /**
     * Gera dinamicamente um Chip para cada área distinta no catálogo, mais um
     * "Todas as áreas" no início. Configura o callback para filtrar.
     */
    private fun criarChipsDeArea() {
        b.chipsAreas.removeAllViews()

        // Chip default: "Todas as áreas"
        val chipTodas = criarChip(getString(R.string.todas_areas), "", checked = true)
        b.chipsAreas.addView(chipTodas)

        val areas = todos.map { it.area }.distinct().sorted()
        for (area in areas) {
            b.chipsAreas.addView(criarChip(area, area))
        }
    }

    private fun criarChip(texto: String, tag: String, checked: Boolean = false): Chip {
        return Chip(this).apply {
            text = texto
            isCheckable = true
            isChecked = checked
            setOnClickListener {
                areaSelecionada = tag
                aplicarFiltros()
            }
        }
    }

    /* ---------- Aplicação dos filtros ---------- */

    private fun aplicarFiltros() {
        val filtrados = todos.filter { livro ->
            if (areaSelecionada.isNotEmpty() && livro.area != areaSelecionada) return@filter false
            if (query.isEmpty()) return@filter true
            livro.titulo.lowercase().contains(query) ||
            livro.autor.lowercase().contains(query) ||
            livro.cota.lowercase().contains(query)
        }
        adapter.submit(filtrados)
        b.contador.text = getString(R.string.count_template, filtrados.size, todos.size)

        // Empty state quando não há resultados
        if (filtrados.isEmpty()) {
            b.listaLivros.visibility = View.GONE
            b.emptyState.visibility  = View.VISIBLE
        } else {
            b.listaLivros.visibility = View.VISIBLE
            b.emptyState.visibility  = View.GONE
        }
    }
}
