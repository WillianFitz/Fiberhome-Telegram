import re
import asyncio
import telnetlib
import time
from telegram.ext import filters
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ConversationHandler,
    CallbackContext,
)

# Definicao dos estados da conversa
ESCOLHER_ACAO, ESCOLHER_ONU, CONFIRMAR_LIBERACAO, RENOMEAR_ONU, CONSULTAR_POTENCIA_OPTICA, \
ESCOLHER_TIPO_OPERACAO, RECEBER_LOCALIZACAO = range(7)# Configuracao da OLT

OLT_IP = "172.31.0.10"
OLT_USERNAME = "GEPON"
OLT_PASSWORD = "GEPON"
OLT_ENABLE_PASSWORD = "GEPON"

# Funcao para conectar a OLT
def connect_to_olt(host, username, password, enable_password):
    try:
        tn = telnetlib.Telnet(host)
        tn.read_until(b"Login:")
        tn.write(username.encode('ascii') + b"\n")
        tn.read_until(b"Password:")
        tn.write(password.encode('ascii') + b"\n")
        tn.read_until(b"> ")
        tn.write(b"enable\n")
        tn.read_until(b"Password:")
        tn.write(enable_password.encode('ascii') + b"\n")
        tn.read_until(b"# ")
        print("Conexao com a OLT estabelecida com sucesso.")
        return tn
    except Exception as e:
        print(f"Erro ao conectar na OLT: {e}")
        return None

# Funcao para descobrir ONUs nao autorizadas
def discover_onus(tn):
    tn.write(b"cd onu\n")
    tn.write(b"show discovery slot all pon all\n")
    time.sleep(5)  # Aguarda a resposta da OLT
    output = tn.read_very_eager().decode('ascii')
    matches = re.findall(r"SLOT\s*=\s*(\d+),\s*PON\s*=\s*(\d+).*?\n\s*(\d+)\s+([\w-]+)\s+([\w\d:]+)", output, re.DOTALL)
    if not matches:
        print("Nenhuma ONU nao autorizada encontrada.")
        return None
    print("ONUs descobertas:")
    onu_list = []
    for idx, match in enumerate(matches, start=1):
        slot, pon, onu_id, onu_type, phy_id = match
        onu_list.append((int(slot), int(pon), int(onu_id), onu_type, phy_id))
        print(f"{idx}. SLOT={slot}, PON={pon}, PHY_ID={phy_id}")
    return onu_list

def normalize_mac(mac):
    """Mantem o formato original esperado pelo sistema e apenas normaliza para maiusculas."""
    mac = mac.strip().upper()  # Remove espacos extras e coloca em maiusculas

    # Verifica se o MAC segue o padrao esperado (exemplo: FHTT07E660F8)
    if re.match(r"^FHTT[0-9A-F]{8}$", mac):  
        return mac  # Retorna o MAC formatado corretamente

    return None  # Retorna None se o MAC for invalido

async def consultar_potencia_optica(update: Update, context: CallbackContext) -> int:
    user_input = update.message.text.strip().lower()  # Normaliza entrada para minusculas

    # Verifica se o usuario deseja sair
    if user_input in ["sair", "3"]:
        await update.message.reply_text("Saindo...")
        return ConversationHandler.END

    # Usa a funcao corrigida para normalizar o MAC
    normalized_mac = normalize_mac(user_input)
    if not normalized_mac:
        await update.message.reply_text(
            "MAC invalido. O formato correto FHTTXXXXXXXX.\n"
            "Digite o MAC novamente ou digite 'sair' para voltar ao menu inicial."
        )
        return CONSULTAR_POTENCIA_OPTICA

    # Chama a funcao para consultar a potencia optica
    optical_power_info = check_optical_power_by_mac(normalized_mac)
    if optical_power_info:
        await update.message.reply_text(f"Potencia optica para a ONU {normalized_mac}:\n{optical_power_info}")
    else:
        await update.message.reply_text(f"Nao foi possi­vel encontrar informacoes para a ONU {normalized_mac}.")

    # Retorna ao menu inicial
    await update.message.reply_text(
        "Escolha uma opcao abaixo:\n"
        "1. Liberar ONU\n"
        "2. Consultar luz da fibra (MAC)\n"
        "3. Sair"
    )
    return ESCOLHER_ACAO

    # Chama a funcao para consultar a potencia optica
    optical_power_info = check_optical_power_by_mac(normalized_mac)
    if optical_power_info:
        await update.message.reply_text(f"Potencia optica para a ONU {normalized_mac}:\n{optical_power_info}")
    else:
        await update.message.reply_text(f"Nao foi possi­vel encontrar informacoes para a ONU {normalized_mac}.")

    # Retorna ao menu inicial
    await update.message.reply_text(
        "Escolha uma opcao abaixo:\n"
        "1. Liberar ONU\n"
        "2. Consultar luz da fibra (MAC)\n"
        "3. Sair"
    )
    return ESCOLHER_ACAO

def check_optical_power_by_mac(phy_id):
    try:
        tn = telnetlib.Telnet("192.168.99.91", 3337, timeout=10)
        tn.write(b"LOGIN:::CTAG::UN=admin,PWD=admin1234;\n")
        time.sleep(1)
        login_response = tn.read_very_eager().decode('ascii')
        if "DENY" in login_response or "invalid parameter format" in login_response:
            print("Falha no login TL1.")
            tn.close()
            return None

        # Localizar Slot e PON pelo MAC
        slot, pon = find_old_pon_for_onu("172.31.0.10", phy_id)
        if not slot or not pon:
            print("ONU nao encontrada na PON antiga.")
            tn.close()
            return None

        # Consultar Potencia optica
        ponid = f"NA-NA-{slot}-{pon}"
        tl1_command_omddm = f"LST-OMDDM::OLTID=172.31.0.10,PONID={ponid},ONUIDTYPE=MAC,ONUID={phy_id}:CTAG::;\n"
        print(f"Comando TL1 gerado para consultar potencia optica: {tl1_command_omddm}")
        tn.write(tl1_command_omddm.encode('ascii'))
        time.sleep(5)
        response_omddm = tn.read_very_eager().decode('ascii')
        print(f"Resposta TL1 (potencia optica): {response_omddm}")  # Log da resposta completa
        tn.close()

        if "COMPLD" in response_omddm:
            rx_power, tx_power = extract_optical_power(response_omddm)
            if rx_power is None or tx_power is None:
                print("Erro ao extrair potencia optica da resposta TL1.")  # Depuracao
                return "Erro ao extrair potencia optica."
            return f"RxPower: {rx_power} dBm\nTxPower: {tx_power} dBm"
        else:
            print("Erro ao consultar potencia optica via TL1.")  # Depuracao
            return "Erro ao consultar potencia optica."
    except Exception as e:
        print(f"Erro ao consultar potencia optica via TL1: {e}")  # Depuracao
        return "Erro ao consultar potencia optica."

def extract_optical_power(response):
    """
    Extrai os valores de RxPower e TxPower da resposta TL1.
    """
    lines = response.splitlines()
    for line in lines:
        # Procura a linha que contem os dados de potencia optica (ignorando cabecalhos)
        if "ONUID" not in line and line.strip() and line.split()[0].isdigit():
            parts = line.split()
            if len(parts) >= 5:  # Garante que ha colunas suficientes
                rx_power = parts[1]  # RxPower esta no i­ndice 1
                tx_power = parts[3]  # TxPower esta no i­ndice 3
                print(f"Valores extrai­dos - RxPower: {rx_power}, TxPower: {tx_power}")  # Depuracao
                return rx_power, tx_power
    print("Nenhuma linha valida encontrada para extrair potencia optica.")  # Depuracao
    return None, None

def query_onu_info_tl1(olt_ip, phy_id):
    try:
        tn = telnetlib.Telnet("192.168.99.91", 3337, timeout=5)
        tn.write(b"LOGIN:::CTAG::UN=admin,PWD=admin1234;\n")
        time.sleep(1)
        login_response = tn.read_very_eager().decode('ascii')
        if "DENY" in login_response or "invalid parameter format" in login_response:
            print("Falha no login TL1.")
            tn.close()
            return None
        tl1_command = f"QUERY-ONUINFO:::CTAG::ONUIDTYPE=MAC,ONUID={phy_id};\n"
        print(f"Comando TL1 gerado para listar ONUs: {tl1_command}")
        tn.write(tl1_command.encode('ascii'))
        time.sleep(1)
        response = tn.read_very_eager().decode('ascii')
        print(f"Resposta TL1:", response)
        tn.close()
        if "DENY" in response or "The NE is not exist" in response:
            print("Erro ao consultar informacoes da ONU via TL1.")
            return None
        return response
    except Exception as e:
        print(f"Erro ao consultar informacoes da ONU via TL1: {e}")
        return None

def desprovision_onu_tl1(olt_ip, slot, pon, phy_id):
    try:
        tn = telnetlib.Telnet("192.168.99.91", 3337, timeout=10)  # Aumentado o timeout
        tn.write(b"LOGIN:::CTAG::UN=admin,PWD=admin1234;\n")
        time.sleep(1)
        login_response = tn.read_very_eager().decode('ascii')
        if "DENY" in login_response or "invalid parameter format" in login_response:
            print("Falha no login TL1.")
            tn.close()
            return False
        ponid = f"NA-NA-{slot}-{pon}"
        tl1_command = f"DEL-ONU::OLTID={olt_ip},PONID={ponid}:CTAG::ONUIDTYPE=MAC,ONUID={phy_id};\n"
        print(f"Comando TL1 gerado para desprovisionar: {tl1_command}")
        tn.write(tl1_command.encode('ascii'))
        time.sleep(5)  # Aguarda a resposta da OLT
        response = tn.read_very_eager().decode('ascii')
        print(f"Resposta TL1 (desprovisionamento): {response}")
        tn.close()
        
        # Verificar se a resposta indica sucesso
        if "COMPLD" in response or "ENDESC=No error" in response or "NO ERROR" in response:
            print(f"ONU {phy_id} desprovisionada com sucesso.")
            return True
        else:
            print(f"Falha ao desprovisionar ONU {phy_id}. Resposta: {response}")
            return False
    except Exception as e:
        print(f"Erro ao desprovisionar ONU via TL1: {e}")
        return False

# Funcao para verificar se a ONU foi removida
def verify_onu_removed_tl1(olt_ip, slot, pon, phy_id, max_attempts=5, delay=2):
    try:
        for attempt in range(max_attempts):
            tn = telnetlib.Telnet("192.168.99.91", 3337, timeout=5)
            tn.write(b"LOGIN:::CTAG::UN=admin,PWD=admin1234;\n")
            time.sleep(1)
            login_response = tn.read_very_eager().decode('ascii')
            if "DENY" in login_response or "invalid parameter format" in login_response:
                print("Falha no login TL1.")
                tn.close()
                return False
            ponid = f"NA-NA-{slot}-{pon}"
            tl1_command = f"QUERY-ONUINFO:::CTAG::ONUIDTYPE=MAC,ONUID={phy_id};\n"
            print(f"Comando TL1 gerado para verificar remocao: {tl1_command}")
            tn.write(tl1_command.encode('ascii'))
            time.sleep(delay)
            response = tn.read_very_eager().decode('ascii')
            print(f"Tentativa {attempt + 1}/{max_attempts} - Resposta TL1 (verificacao): {response}")
            tn.close()
            
            if phy_id not in response:
                print(f"A ONU {phy_id} foi removida com sucesso.")
                return True
            print(f"A ONU {phy_id} ainda esta presente na PON. Tentando novamente...")
            time.sleep(delay)
        print(f"Falha ao remover a ONU {phy_id} apos {max_attempts} tentativas.")
        return False
    except Exception as e:
        print(f"Erro ao verificar remocao da ONU via TL1: {e}")
        return False

def find_old_pon_for_onu(olt_ip, phy_id):
    print("Procurando a PON antiga da ONU...")

    response = query_onu_info_tl1(olt_ip, phy_id)  # Executa a consulta TL1

    if response:
        # Normaliza para facilitar a busca (case-insensitive)
        normalized_response = response.lower()
        normalized_phy_id = phy_id.lower()

        if normalized_phy_id in normalized_response:  # Verifica se o MAC esta na resposta
            lines = response.splitlines()
            
            print("\n Depuracao: Exibindo linhas da resposta TL1:")
            for line in lines:
                print(line)  # Exibe todas as linhas para depuracao

                if normalized_phy_id in line.lower():  # Busca a linha correta (case-insensitive)
                    print(f"\nLinha encontrada: {line}\n")  # Depuracao: imprime a linha com a ONU

                    # Expressao regular para capturar SlotNo e PonNo
                    match = re.search(r'AN\d{4,}-\S+\s+(\d+)\s+(\d+)', line)

                    if match:
                        slot_found = int(match.group(1))  # Primeiro numero encontrado  no Slot
                        pon_found = int(match.group(2))   # Segundo numero na Pon

                        print(f"ONU encontrada na PON antiga: SLOT={slot_found}, PON={pon_found}")
                        return slot_found, pon_found
                    else:
                        print("? Erro: Nao foi possi­vel extrair SLOT e PON corretamente.")
                        return None, None

    print(" ONU nao encontrada na resposta TL1.")
    return None, None

# Funcao para verificar se a ONU ja existe
def check_onu_exists(tn, phy_id):
    command = f"LST-ONU:::CTAG::;\n"
    tn.write(command.encode('ascii'))
    time.sleep(1)
    response = tn.read_very_eager().decode('ascii')
    if phy_id in response:
        print(f"A ONU com PHY ID {phy_id} ja esta provisionada.")
        return True
    return False

# Funcao para obter o proximo ID disponi­vel para a ONU
def get_next_onu_id_tl1(olt_ip, slot, pon):
    """
    Consulta as ONUs provisionadas na PON especi­fica usando TL1 e retorna o proximo ID disponi­vel.
    """
    try:
        # Conectar ao servidor TL1
        tn = telnetlib.Telnet("192.168.99.91", 3337, timeout=5)
        tn.write(b"LOGIN:::CTAG::UN=admin,PWD=admin1234;\n")
        time.sleep(1)
        login_response = tn.read_very_eager().decode('utf-8', errors='ignore')
        if "DENY" in login_response or "invalid parameter format" in login_response:
            print("Falha no login TL1.")
            tn.close()
            return None

        # Construir o comando TL1 para listar ONUs na PON especifica
        ponid = f"NA-NA-{slot}-{pon}"
        tl1_command = f"LST-ONU::OLTID=172.31.0.10,PONID={ponid}:CTAG::;\n"
        print(f"Comando TL1 gerado para listar ONUs: {tl1_command}")
        tn.write(tl1_command.encode('ascii'))
        time.sleep(1)
        response = tn.read_very_eager().decode('utf-8', errors='ignore')
        print(f"Resposta TL1:", response)

        # Fechar a conexao TL1
        tn.close()

        # Verificar se a resposta contem informacoes de ONUs
        if "DENY" in response or "The NE is not exist" in response:
            print("Erro ao consultar ONUs via TL1.")
            return None

        # Extrair IDs das ONUs da resposta TL1
        used_ids = set()
        lines = response.splitlines()
        for line in lines:
            parts = line.split()
            if len(parts) >= 3 and parts[2].isdigit():  # Verifica se o terceiro campo um numero (ONUNO)
                onu_id = int(parts[2])  # ONUNO esta no i­ndice 2
                used_ids.add(onu_id)
        print(f"IDs ja utilizados: {sorted(used_ids)}")  # Log para depuracao

        # Encontrar o menor ID nao utilizado dentro do intervalo de 1 a 128
        for next_id in range(1, 129):
            if next_id not in used_ids:
                print(f"Proximo ONU ID disponivel: {next_id}")  # Log para depuracao
                return next_id

        print("Erro: Todos os 128 IDs estao ocupados!")
        return None  # Retorna None se nao houver IDs disponi­veis
    except Exception as e:
        print(f"Erro ao consultar IDs de ONUs via TL1: {e}")
        return None

# Funcao para provisionar a ONU
def provision_onu(tn, slot, pon, onu_type, phy_id, onu_id, vlan):
    tn.write(f"set authorization slot {slot} pon {pon} type {onu_type} onuid {onu_id} phy_id {phy_id} password null\n".encode('ascii'))
    time.sleep(2)
    tn.write(f"set whitelist phy_addr address {phy_id} password null action add slot {slot} pon {pon} onu {onu_id} type {onu_type}\n".encode('ascii'))
    time.sleep(2)
    tn.write(b"cd lan\n")
    time.sleep(1)
    tn.write(f"add gepon slot {slot} pon {pon} onu {onu_id} port 1 service number 1\n".encode('ascii'))
    time.sleep(1)
    tn.write(f"set ep sl {slot} p {pon} o {onu_id} p 1 serv num 1\n".encode('ascii'))
    time.sleep(1)
    tn.write(f"set ep sl {slot} p {pon} o {onu_id} p 1 serv 1 vlan_m tag 0 33024 {vlan}\n".encode('ascii'))
    time.sleep(1)
    tn.write(f"apply onu {slot} {pon} {onu_id} vlan\n".encode('ascii'))
    time.sleep(5)

# Funcao para renomear a ONU via TL1
def rename_onu_tl1(olt_ip, slot, pon, phy_id, onu_name):
    try:
        tn = telnetlib.Telnet("192.168.99.91", 3337, timeout=5)
        tn.write(b"LOGIN:::CTAG::UN=admin,PWD=admin1234;\n")
        time.sleep(1)
        login_response = tn.read_very_eager().decode('ascii')
        if "DENY" in login_response or "invalid parameter format" in login_response:
            print("Falha no login TL1.")
            tn.close()
            return False
        ponid = f"NA-NA-{slot}-{pon}"
        tl1_command = f"CFG-ONUNAMEANDDESC::OLTID={olt_ip},PONID={ponid},ONUIDTYPE=MAC,ONUID={phy_id}:CTAG::ONUNAME={onu_name};\n"
        print(f"Comando TL1 gerado para renomear ONU: {tl1_command}")
        tn.write(tl1_command.encode('ascii'))
        time.sleep(5)
        response = tn.read_very_eager().decode('ascii')
        print(f"Resposta TL1 (renomeacao): {response}")
        tn.close()
        if "COMPLD" in response:
            print(f"ONU renomeada com sucesso: SLOT={slot}, PON={pon}, PHY_ID={phy_id}, Nome={onu_name}")
            return True
        else:
            print(f"Falha ao renomear ONU: {response}")
            return False
    except Exception as e:
        print(f"Erro ao renomear ONU via TL1: {e}")
        return False

def check_optical_power(olt_ip, slot, pon, phy_id):
    """
    Consulta a potencia optica (luz da fibra) da ONU usando o comando TL1 LST-OMDDM.
    """
    try:
        tn = telnetlib.Telnet("192.168.99.91", 3337, timeout=5)
        tn.write(b"LOGIN:::CTAG::UN=admin,PWD=admin1234;\n")
        time.sleep(1)
        login_response = tn.read_very_eager().decode('ascii')
        if "DENY" in login_response or "invalid parameter format" in login_response:
            print("Falha no login TL1.")
            tn.close()
            return None

        # Construir o comando TL1 para consultar a potencia optica
        ponid = f"NA-NA-{slot}-{pon}"
        tl1_command = f"LST-OMDDM::OLTID={olt_ip},PONID={ponid},ONUIDTYPE=MAC,ONUID={phy_id}:CTAG::;\n"
        print(f"Comando TL1 gerado para consultar potencia optica: {tl1_command}")
        tn.write(tl1_command.encode('ascii'))
        time.sleep(5)  # Aguarda a resposta da OLT
        response = tn.read_very_eager().decode('ascii')
        print(f"Resposta TL1 (potencia Optica): {response}")
        tn.close()

        # Verificar se a resposta contem informacoes validas
        if "COMPLD" in response:
            # Extrair os valores relevantes da resposta
            rx_power = None
            tx_power = None
            lines = response.splitlines()
            for line in lines:
                if line.strip().startswith("1"):  # Procura a linha que comeca com o ID da ONU (1)
                    parts = line.split()
                    if len(parts) >= 5:  # Garante que ha colunas suficientes
                        rx_power = parts[1]  # RxPower esta no i­ndice 1
                        tx_power = parts[3]  # TxPower esta no i­ndice 3
                    break  # Sair do loop assim que encontrar os valores

            if rx_power and tx_power:
                print(f"Potencia Optica: RxPower={rx_power}, TxPower={tx_power}")
                return f"RxPower: {rx_power} dBm\nTxPower: {tx_power} dBm"
            else:
                print("Erro ao extrair potoncia Optica da resposta TL1.")
                return "Nao foi possi­vel extrair a potencia Optica."
        else:
            print("Erro ao consultar potencia Optica via TL1.")
            return "Erro ao consultar potencia Optica."
    except Exception as e:
        print(f"Erro ao consultar potencia Optica via TL1: {e}")
        return "Erro ao consultar potencia Optica."

def save_database_tl1(tn):
    """
    Salva a base de dados da OLT via Telnet.
    """
    if tn:
        try:
            tn.write(b"save\n")
            time.sleep(1)
            tn.read_until(b"# ")
            print("Base de dados salva na OLT.")
        except Exception as e:
            print(f"Erro ao salvar a base de dados da OLT: {e}")
    else:
        print("Erro: Conexao Telnet nao esta disponi­vel.")

# Comando /start
async def start(update: Update, context: CallbackContext) -> int:
    await update.message.reply_text(
        "Bem-vindo! Escolha uma opcao abaixo:\n"
        "1. Liberar ONU\n"
        "2. Consultar luz da fibra (MAC)\n"
        "3. Sair"
    )
    return ESCOLHER_ACAO

# Processar a escolha do usuario
async def escolher_acao(update: Update, context: CallbackContext) -> int:
    escolha = update.message.text.strip()
    if escolha == "3":
        await update.message.reply_text("Saindo...")
        return ConversationHandler.END
    elif escolha == "1":
        tn = connect_to_olt(OLT_IP, OLT_USERNAME, OLT_PASSWORD, OLT_ENABLE_PASSWORD)
        if not tn:
            await update.message.reply_text("Erro ao conectar a OLT.")
            return ConversationHandler.END
        onu_list = discover_onus(tn)
        if not onu_list:
            await update.message.reply_text(
                "Nenhuma ONU nao autorizada foi encontrada.\n"
                "Escolha uma opcao abaixo:\n"
                "1. Tentar encontrar ONUs novamente\n"
                "3. Sair"
            )
            return ESCOLHER_ACAO  # Retorna ao estado de escolha inicial
        onu_text = "Escolha a ONU que deseja liberar:\n"
        for idx, (slot, pon, _, _, phy_id) in enumerate(onu_list, start=1):
            onu_text += f"{idx}. SLOT={slot}, PON={pon}, PHY_ID={phy_id}\n"
        await update.message.reply_text(onu_text)
        context.user_data["tn"] = tn
        context.user_data["onu_list"] = onu_list
        return ESCOLHER_ONU
    elif escolha == "2":
        await update.message.reply_text("Digite o MAC da ONU para consultar a luz da fibra:")
        return CONSULTAR_POTENCIA_OPTICA
    else:
        await update.message.reply_text("Opcao invalida. Por favor, escolha uma opcao valida.")
        return ESCOLHER_ACAO

# Processar a escolha da ONU
async def escolher_onu(update: Update, context: CallbackContext) -> int:
    escolha = update.message.text.strip()
    tn = context.user_data.get("tn")
    onu_list = context.user_data.get("onu_list")

    # Se nenhuma ONU foi encontrada, oferecer opcoes para tentar novamente ou sair
    if not onu_list or len(onu_list) == 0:
        await update.message.reply_text(
            "Nenhuma ONU nao autorizada foi encontrada.\n"
            "Escolha uma opcao abaixo:\n"
            "1. Tentar encontrar ONUs novamente\n"
            "2. Sair"
        )
        return ESCOLHER_ACAO  # Retorna ao estado de escolha inicial

    try:
        selected_index = int(escolha) - 1
        slot, pon, _, onu_type, phy_id = onu_list[selected_index]
    except (ValueError, IndexError):
        await update.message.reply_text("Escolha invalida. Por favor, escolha um numero valido.")
        return ESCOLHER_ONU

    if check_onu_exists(tn, phy_id):
        await update.message.reply_text(f"A ONU com PHY ID {phy_id} ja esta provisionada.")
        tn.close()
        return ConversationHandler.END

    context.user_data["slot"] = slot
    context.user_data["pon"] = pon
    context.user_data["onu_type"] = onu_type
    context.user_data["phy_id"] = phy_id
    await update.message.reply_text(f"Confirma a liberacao da ONU com PHY ID {phy_id}? (sim/nao)")
    return CONFIRMAR_LIBERACAO

async def confirmar_liberacao(update: Update, context: CallbackContext) -> int:
    resposta = update.message.text.strip().lower()
    if resposta == "sim":
        tn = context.user_data.get("tn")
        slot_new = context.user_data.get("slot")  # Novo slot
        pon_new = context.user_data.get("pon")   # Nova PON
        onu_type = context.user_data.get("onu_type")
        phy_id = context.user_data.get("phy_id")

        # Mensagem informando que vamos garantir que a ONU esta desprovisionada
        await update.message.reply_text(
            "Vou garantir pra voce que sua ONU esta desprovisionada ja..."
        )

        # Verificar se a ONU ja esta provisionada em outra PON
        slot_old, pon_old = find_old_pon_for_onu(OLT_IP, phy_id)
        if slot_old is not None and pon_old is not None:
            print(f"Desprovisionando ONU da PON antiga: SLOT={slot_old}, PON={pon_old}")
            if not desprovision_onu_tl1(OLT_IP, slot_old, pon_old, phy_id):
                await update.message.reply_text("Falha ao desprovisionar a ONU da PON antiga. Operacao cancelada.")
                tn.close()
                return ConversationHandler.END

            # Verificar se a ONU foi realmente removida
            if not verify_onu_removed_tl1(OLT_IP, slot_old, pon_old, phy_id):
                await update.message.reply_text("A ONU nao foi removida corretamente. Operacao cancelada.")
                tn.close()
                return ConversationHandler.END

        # Mensagem informando que a ONU foi desprovisionada
        await update.message.reply_text(
            f"A ONU com PHY ID {phy_id} foi desprovisionada com sucesso e esta pronta para ser liberada!"
        )
        time.sleep(10)  # Aguardar mais tempo para garantir que o desprovisionamento seja conclui­do

        # Continuar com o provisionamento na nova PON
        onu_id = get_next_onu_id_tl1(tn, slot_new, pon_new)
        if not onu_id:
            await update.message.reply_text("Nao ha IDs disponi­veis para provisionar a ONU.")
            tn.close()
            return ConversationHandler.END

        vlan = slot_new * 100 + pon_new
        provision_onu(tn, slot_new, pon_new, onu_type, phy_id, onu_id, vlan)

        # Aguardar um tempo para que a OLT processe a ONU provisionada
        await update.message.reply_text("Aguarde enquanto a OLT processa a ONU...")
        time.sleep(10)  # Delay de 10 segundos para garantir que a OLT atualize os dados

        # Consultar a potencia Optica apos o provisionamento
        optical_power_info = check_optical_power(OLT_IP, slot_new, pon_new, phy_id)
        await update.message.reply_text(
            f"ONU provisionada com sucesso!\nPotencia Optica: \n{optical_power_info}\n Agora, digite o nome para a ONU:"
        )
        return RENOMEAR_ONU
    else:
        await update.message.reply_text("Liberacao cancelada.")
        return ConversationHandler.END

# Renomear a ONU
async def renomear_onu(update: Update, context: CallbackContext) -> int:
    onu_name = update.message.text.strip()
    tn = context.user_data.get("tn")
    slot = context.user_data.get("slot")
    pon = context.user_data.get("pon")
    phy_id = context.user_data.get("phy_id")
    
    # Renomear a ONU via TL1
    rename_onu_tl1(OLT_IP, slot, pon, phy_id, onu_name)
    save_database_tl1(tn)
    tn.close()

    await update.message.reply_text(f"ONU renomeada para '{onu_name}' e salva com sucesso!")
    
    # Perguntar ao tecnico se Instalacao ou Troca de Equipamento
    await update.message.reply_text(
        "Escolha o tipo de operacao:\n"
        "1. Instalacao\n"
        "2. Troca de Equipamento"
    )
    return ESCOLHER_TIPO_OPERACAO

async def escolher_tipo_operacao(update: Update, context: CallbackContext) -> int:
    escolha = update.message.text.strip()
    
    if escolha == "1":  # Instalacao
        await update.message.reply_text("Por favor, envie a localizacao da instalacao.")
        return RECEBER_LOCALIZACAO
    elif escolha == "2":  # Troca de Equipamento
        await update.message.reply_text("Operacao de Troca de Equipamento finalizada.")
        return ConversationHandler.END
    else:
        await update.message.reply_text("Opcao invalida. Por favor, escolha '1' para Instalacao ou '2' para Troca de Equipamento.")
        return ESCOLHER_TIPO_OPERACAO

async def receber_localizacao(update: Update, context: CallbackContext) -> int:
    location = update.message.location
    
    if location:
        latitude = location.latitude
        longitude = location.longitude
        
        # Exibir as coordenadas para o tÃÂ©cnico
        await update.message.reply_text(
            f"Localizacao recebida com sucesso!\n"
            f"Latitude: {latitude}\n"
            f"Longitude: {longitude}\n"
            "Coordenadas para o tecnico N1 fazer o geogrid.\n"
            f"-------------------------------------------------------\n"
            f"LIBERACAO CONCLUIDA \n" 
            f"LIGAR PARA 30331000 FAZER O GEOGRID E SOLICITAR LIBERACAO"
        )
    else:
        await update.message.reply_text("Localizacao invalida. Por favor, tente novamente.")
    
    return ConversationHandler.END

# Cancelar a operacao
async def cancelar(update: Update, context: CallbackContext) -> int:
    await update.message.reply_text("Operacao cancelada. Para iniciar novamente, use /start.")
    return ConversationHandler.END

# Funcao para processar mensagens de grupo
async def processar_mensagem_grupo(update: Update, context: CallbackContext) -> None:
    message = update.message.text.strip()
    chat_id = update.message.chat_id
    user = update.message.from_user.username or update.message.from_user.first_name

    # Verifica se a mensagem a um comando especi­fico
    if message.startswith("/startonu"):
        await update.message.reply_text(f"Ola {user}, iniciando o processo de liberacao de ONU...")
        return await start(update, context)

    # Verifica se o bot foi mencionado na mensagem
    if update.message.entities and update.message.entities[0].type == "mention":
        mentioned_bot = update.message.text.split()[0][1:]  # Remove o "@" da mencao
        if mentioned_bot == context.bot.username:  # Verifica se o bot foi mencionado
            await update.message.reply_text(f"Ola {user}, use /startonu para iniciar.")
            return ConversationHandler.END

    # Ignora outras mensagens no grupo
    return ConversationHandler.END

# Iniciar o bot
def iniciar_bot():
    app = ApplicationBuilder().token("TOKENBOTTELEGRAM").build()
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("startonu", start),
            MessageHandler(filters.ChatType.GROUP | filters.ChatType.SUPERGROUP, processar_mensagem_grupo),
        ],
        states={
            ESCOLHER_ACAO: [MessageHandler(filters.TEXT & ~filters.COMMAND, escolher_acao)],
            ESCOLHER_ONU: [MessageHandler(filters.TEXT & ~filters.COMMAND, escolher_onu)],
            CONFIRMAR_LIBERACAO: [MessageHandler(filters.TEXT & ~filters.COMMAND, confirmar_liberacao)],
            RENOMEAR_ONU: [MessageHandler(filters.TEXT & ~filters.COMMAND, renomear_onu)],
            CONSULTAR_POTENCIA_OPTICA: [MessageHandler(filters.TEXT & ~filters.COMMAND, consultar_potencia_optica)],
            ESCOLHER_TIPO_OPERACAO: [MessageHandler(filters.TEXT & ~filters.COMMAND, escolher_tipo_operacao)],
            RECEBER_LOCALIZACAO: [MessageHandler(filters.LOCATION, receber_localizacao)],
        },
        fallbacks=[CommandHandler("cancel", cancelar)],
    )
    app.add_handler(conv_handler)
    print("Bot iniciado! Aguardando mensagens...")
    app.run_polling()

if __name__ == "__main__":
    iniciar_bot()