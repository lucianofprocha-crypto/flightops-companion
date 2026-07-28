import sys

from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QGroupBox,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        # Configuração da janela
        self.setWindowTitle("FlightOps Companion")
        self.resize(800, 600)

        # ==========================
        # Barra de Menu
        # ==========================
        menu = self.menuBar()

        arquivo = menu.addMenu("Arquivo")
        ferramentas = menu.addMenu("Ferramentas")
        ajuda = menu.addMenu("Ajuda")

        # Widget principal
        central = QWidget()
        self.setCentralWidget(central)

        # Layout principal
        layout = QVBoxLayout()
        central.setLayout(layout)

        # ==========================
        # Título
        # ==========================
        titulo = QLabel("Airport Intelligence")
        titulo.setStyleSheet("""
            font-size: 28px;
            font-weight: bold;
        """)

        layout.addWidget(titulo)

        # ==========================
        # ICAO
        # ==========================
        aeroporto = QGroupBox("ICAO")
        aeroporto_layout = QVBoxLayout()

        self.icao = QComboBox()

        self.icao.addItems([
            "SBJH",
            "SBKP",
            "SBGR",
            "SBSJ",
            "SBSP",
        ])

        aeroporto_layout.addWidget(self.icao)

        aeroporto.setLayout(aeroporto_layout)

        layout.addWidget(aeroporto)

        # ==========================
        # Período
        # ==========================
        periodo = QGroupBox("Período")

        periodo_layout = QVBoxLayout()

        self.d30 = QRadioButton("Últimos 30 dias")
        self.d365 = QRadioButton("Últimos 365 dias")
        self.d5 = QRadioButton("Últimos 5 anos")

        self.d365.setChecked(True)

        periodo_layout.addWidget(self.d30)
        periodo_layout.addWidget(self.d365)
        periodo_layout.addWidget(self.d5)

        periodo.setLayout(periodo_layout)

        layout.addWidget(periodo)

        # ==========================
        # Botão
        # ==========================
        self.botao = QPushButton("ANALISAR")
        self.botao.setMinimumHeight(45)

        self.botao.clicked.connect(self.analisar)

        layout.addWidget(self.botao)

    # ==========================================
    # Evento do botão ANALISAR
    # ==========================================
    def analisar(self):

        if self.d30.isChecked():
            periodo = "Últimos 30 dias"

        elif self.d365.isChecked():
            periodo = "Últimos 365 dias"

        else:
            periodo = "Últimos 5 anos"

        QMessageBox.information(
            self,
            "FlightOps Companion",
            f"""Airport Intelligence

Aeroporto: {self.icao.currentText()}

Período: {periodo}

Em breve iniciaremos a análise dos METAR históricos.
"""
        )


# ==========================================
# Inicialização do programa
# ==========================================

app = QApplication(sys.argv)

janela = MainWindow()
janela.show()

app.exec()