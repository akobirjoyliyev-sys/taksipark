param(
  [string]$SdkRoot = 'D:\Android\sdk',
  [string]$JdkRoot = $env:JAVA_HOME,
  [string]$BuildDir = (Join-Path $PSScriptRoot 'build'),
  [string]$OutputApk = (Join-Path $PSScriptRoot '..\NAVO-Taxi.apk')
)
$ErrorActionPreference = 'Stop'
$buildTools = Join-Path $SdkRoot 'build-tools\34.0.0'
$androidJar = Join-Path $SdkRoot 'platforms\android-34\android.jar'
if (!(Test-Path -LiteralPath $androidJar)) { throw 'Android SDK platform 34 kerak.' }
if (!(Test-Path -LiteralPath (Join-Path $JdkRoot 'bin\javac.exe'))) { throw 'JAVA_HOME yoki JdkRoot orqali JDK 17 manzilini kiriting.' }
New-Item -ItemType Directory -Force -Path $BuildDir,(Join-Path $BuildDir 'classes'),(Join-Path $BuildDir 'dex') | Out-Null
$BuildDir = (Resolve-Path -LiteralPath $BuildDir).Path
function Run-Tool([string]$tool, [string[]]$arguments) {
  & $tool @arguments
  if ($LASTEXITCODE -ne 0) { throw "Build xatosi: $tool ($LASTEXITCODE)" }
}
Run-Tool (Join-Path $buildTools 'aapt.exe') @('package','-f','-m','-M',(Join-Path $PSScriptRoot 'AndroidManifest.xml'),'-S',(Join-Path $PSScriptRoot 'res'),'-A',(Join-Path $PSScriptRoot '..\public'),'-I',$androidJar,'-F',(Join-Path $BuildDir 'unsigned.apk'))
$source = Join-Path $PSScriptRoot 'src\uz\navo\taksopark\MainActivity.java'
Run-Tool (Join-Path $JdkRoot 'bin\javac.exe') @('-encoding','UTF-8','-source','8','-target','8','-classpath',$androidJar,'-d',(Join-Path $BuildDir 'classes'),$source)
$classes = @(Get-ChildItem -LiteralPath (Join-Path $BuildDir 'classes') -Recurse -Filter '*.class' | ForEach-Object FullName)
Run-Tool (Join-Path $JdkRoot 'bin\java.exe') (@('-cp',(Join-Path $buildTools 'lib\d8.jar'),'com.android.tools.r8.D8','--lib',$androidJar,'--min-api','26','--output',(Join-Path $BuildDir 'dex')) + $classes)
Push-Location (Join-Path $BuildDir 'dex')
try { Run-Tool (Join-Path $buildTools 'aapt.exe') @('add',(Join-Path $BuildDir 'unsigned.apk'),'classes.dex') } finally { Pop-Location }
Run-Tool (Join-Path $buildTools 'zipalign.exe') @('-f','4',(Join-Path $BuildDir 'unsigned.apk'),(Join-Path $BuildDir 'aligned.apk'))
$key = Join-Path $BuildDir 'test-signing.jks'
if (!(Test-Path -LiteralPath $key)) {
  Run-Tool (Join-Path $JdkRoot 'bin\keytool.exe') @('-genkeypair','-keystore',$key,'-storepass','android','-keypass','android','-alias','navotest','-dname','CN=NAVO Development, O=Local Development, C=UZ','-keyalg','RSA','-keysize','2048','-validity','3650','-noprompt')
}
Run-Tool (Join-Path $JdkRoot 'bin\java.exe') @('-jar',(Join-Path $buildTools 'lib\apksigner.jar'),'sign','--ks',$key,'--ks-pass','pass:android','--key-pass','pass:android','--out',$OutputApk,(Join-Path $BuildDir 'aligned.apk'))
Run-Tool (Join-Path $JdkRoot 'bin\java.exe') @('-jar',(Join-Path $buildTools 'lib\apksigner.jar'),'verify','--verbose',$OutputApk)
Write-Output "APK tayyor: $OutputApk"
