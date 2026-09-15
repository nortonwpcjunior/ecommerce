# Versao Windows do run_services.sh (PowerShell).
# Sobe os 6 processos nao-interativos em background, com log em logs\.
# O ms_principal fica de fora: rode-o em primeiro plano, e ele e a interface.
#
#   .\run_services.ps1 start    # sobe estoque, pagamento, entrega, promocoes, C1, C2
#   .\run_services.ps1 stop     # derruba todos
#   .\run_services.ps1 logs     # acompanha os logs (Ctrl+C para sair)
#
# Se o PowerShell recusar o script por politica de execucao, rode assim:
#   powershell -ExecutionPolicy Bypass -File .\run_services.ps1 start
#
# A venv nao precisa estar dentro do projeto. Para apontar para outra:
#   .\run_services.ps1 start -Python C:\caminho\da\venv\Scripts\python.exe
#
# Para a defesa, prefira 7 terminais separados (ver README).

param([string]$Comando = "start", [string]$Python = "")

$ErrorActionPreference = "Stop"

$Raiz     = Split-Path -Parent $MyInvocation.MyCommand.Path
$PastaLog = Join-Path $Raiz "logs"
$Servicos = @("ms_estoque", "ms_pagamento", "ms_entrega", "ms_promocoes",
              "consumidor_c1", "consumidor_c2")


# Acha o interpretador, em ordem de preferencia. A venv nem sempre fica dentro
# do projeto (VS Code costuma guardar em uma pasta central), entao caminho fixo
# nao serve.
function Resolve-Python {
    $candidatos = @()
    if ($Python)          { $candidatos += $Python }
    if ($env:PYTHON_EXE)  { $candidatos += $env:PYTHON_EXE }
    $candidatos += (Join-Path $Raiz ".venv\Scripts\python.exe")   # venv no projeto
    if ($env:VIRTUAL_ENV) {                                        # venv ativada
        $candidatos += (Join-Path $env:VIRTUAL_ENV "Scripts\python.exe")
    }

    foreach ($c in $candidatos) {
        if ($c -and (Test-Path $c)) { return (Resolve-Path $c).Path }
    }

    # Ultimo recurso: o python do PATH. Pode ser o global, sem as dependencias;
    # a checagem de import logo abaixo pega esse caso.
    $noPath = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($noPath) { return $noPath.Source }

    return $null
}


# Roda um comando externo sem deixar o $ErrorActionPreference='Stop' converter
# a saida de stderr em excecao. Devolve o codigo de saida.
function Invoke-Python([string]$exe, [string[]]$argumentos) {
    $anterior = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $exe @argumentos 2>&1 | Out-Null
        return $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $anterior
    }
}


# Devolve o processo vivo do PID gravado, ou $null. Confere tambem o nome:
# no Windows o PID e reciclado rapido, e um PID antigo pode ser de outro app.
function Get-ProcessoServico([string]$servico) {
    $arquivoPid = Join-Path $PastaLog "$servico.pid"
    if (-not (Test-Path $arquivoPid)) { return $null }

    $numero = 0
    if (-not [int]::TryParse((Get-Content $arquivoPid -Raw).Trim(), [ref]$numero)) {
        return $null
    }

    $processo = Get-Process -Id $numero -ErrorAction SilentlyContinue
    if ($processo -and $processo.ProcessName -like "python*") { return $processo }
    return $null
}


function Start-Servicos {
    $Py = Resolve-Python
    if (-not $Py) {
        Write-Host "[ERRO] Nenhum interpretador Python encontrado."
        Write-Host "       Crie a venv:  py -m venv .venv"
        Write-Host "                     .venv\Scripts\python -m pip install -r requirements.txt"
        Write-Host "       Ou aponte para uma existente:"
        Write-Host "                     .\run_services.ps1 start -Python C:\caminho\Scripts\python.exe"
        exit 1
    }

    # Sem isso, um interpretador errado sobe os 6 processos, todos morrem no
    # import e o erro fica escondido nas janelas ocultas.
    if ((Invoke-Python $Py @("-c", "import pika, cryptography")) -ne 0) {
        Write-Host "[ERRO] O interpretador encontrado nao tem as dependencias:"
        Write-Host "       $Py"
        Write-Host "       Instale com:  `"$Py`" -m pip install -r requirements.txt"
        Write-Host "       Ou use outro:  .\run_services.ps1 start -Python C:\caminho\Scripts\python.exe"
        exit 1
    }

    Write-Host "Python: $Py"
    Write-Host ""

    New-Item -ItemType Directory -Force -Path $PastaLog | Out-Null

    foreach ($s in $Servicos) {
        $processo = Get-ProcessoServico $s
        if ($processo) {
            Write-Host "  $s ja esta rodando (pid $($processo.Id))"
            continue
        }

        # O logging do Python escreve em stderr, entao os eventos caem em
        # <servico>.log. O Start-Process nao aceita o mesmo arquivo para as
        # duas saidas, por isso o stdout vai para <servico>.out.log.
        $novo = Start-Process -FilePath $Py `
                              -ArgumentList "-u", "-m", "$s.main" `
                              -WorkingDirectory $Raiz `
                              -WindowStyle Hidden `
                              -PassThru `
                              -RedirectStandardError  (Join-Path $PastaLog "$s.log") `
                              -RedirectStandardOutput (Join-Path $PastaLog "$s.out.log")

        Set-Content -Path (Join-Path $PastaLog "$s.pid") -Value $novo.Id
        Write-Host "  $s iniciado (pid $($novo.Id)) -> logs\$s.log"
    }

    Write-Host ""
    Write-Host "Agora rode a interface:  `"$Py`" -m ms_principal.main"
}


function Stop-Servicos {
    foreach ($s in $Servicos) {
        $arquivoPid = Join-Path $PastaLog "$s.pid"
        if (-not (Test-Path $arquivoPid)) { continue }

        $processo = Get-ProcessoServico $s
        if ($processo) {
            Stop-Process -Id $processo.Id -Force
            Write-Host "  $s parado"
        } else {
            Write-Host "  $s nao estava rodando"
        }
        Remove-Item $arquivoPid -Force
    }
}


# Equivalente ao 'tail -f logs/*.log': le so o que foi acrescentado desde a
# ultima passagem e prefixa cada linha com o nome do servico. Abre o arquivo
# com FileShare.ReadWrite para nao travar o processo que esta escrevendo.
function Show-Logs {
    if (-not (Test-Path $PastaLog)) {
        Write-Host "Nada em logs\ ainda. Rode:  .\run_services.ps1 start"
        return
    }

    Write-Host "Acompanhando logs\*.log (Ctrl+C para sair)"
    Write-Host ""

    $posicoes = @{}
    while ($true) {
        foreach ($arquivo in Get-ChildItem -Path $PastaLog -Filter *.log | Sort-Object Name) {
            $inicio = 0
            if ($posicoes.ContainsKey($arquivo.Name)) { $inicio = $posicoes[$arquivo.Name] }
            if ($arquivo.Length -lt $inicio) { $inicio = 0 }   # arquivo recriado
            if ($arquivo.Length -le $inicio) { continue }

            $fluxo = [System.IO.File]::Open($arquivo.FullName, "Open", "Read", "ReadWrite")
            try {
                $null = $fluxo.Seek($inicio, "Begin")
                $leitor = New-Object System.IO.StreamReader($fluxo)
                $texto  = $leitor.ReadToEnd()
                $posicoes[$arquivo.Name] = $fluxo.Position
            } finally {
                $fluxo.Close()
            }

            foreach ($linha in ($texto -split "`r?`n")) {
                if ($linha -ne "") {
                    Write-Host ("[{0}] {1}" -f $arquivo.BaseName, $linha)
                }
            }
        }
        Start-Sleep -Milliseconds 500
    }
}


switch ($Comando.ToLower()) {
    "start" { Start-Servicos }
    "stop"  { Stop-Servicos }
    "logs"  { Show-Logs }
    default {
        Write-Host "uso: .\run_services.ps1 {start|stop|logs}"
        exit 1
    }
}

