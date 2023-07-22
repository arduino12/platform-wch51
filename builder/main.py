import sys
from os.path import join

from SCons.Script import ARGUMENTS, AlwaysBuild, Default, DefaultEnvironment


def __getSize(size_type, env):
    # FIXME: i don't really know how to do this right. see:
    #        https://community.platformio.org/t/missing-integers-in-board-extra-flags-in-board-json/821
    return str(
        env.BoardConfig().get(
            "build",
            {
                # defaults
                "size_heap": 1024,
                "size_iram": 256,
                "size_xram": 65536,
                "size_code": 65536,
            },
        )[size_type]
    )


def _parseSdccFlags(flags):
    assert flags
    if isinstance(flags, list):
        flags = " ".join(flags)
    flags = str(flags)
    parsed_flags = []
    unparsed_flags = []
    prev_token = ""
    for token in flags.split(" "):
        if prev_token.startswith("--") and not token.startswith("-"):
            parsed_flags.extend([prev_token, token])
            prev_token = ""
            continue
        if prev_token:
            unparsed_flags.append(prev_token)
        prev_token = token
    unparsed_flags.append(prev_token)
    return (parsed_flags, unparsed_flags)


env = DefaultEnvironment()
platform = env.PioPlatform()
board_config = env.BoardConfig()

env.Replace(
    AR="sdar",
    AS="sdas8051",
    CC="sdcc",
    LD="sdld",
    RANLIB="sdranlib",
    OBJCOPY="sdobjcopy",
    OBJSUFFIX=".rel",
    LIBSUFFIX=".lib",
    SIZETOOL=join(platform.get_dir(), "builder", "size.py"),
    SIZECHECKCMD="$PYTHONEXE $SIZETOOL $SOURCES",
    SIZEPRINTCMD='"$PYTHONEXE" $SIZETOOL $SOURCES',
    SIZEPROGREGEXP=r"^ROM/EPROM/FLASH\s+[a-fx\d]+\s+[a-fx\d]+\s+(\d+).*",
    PROGNAME="firmware",
    PROGSUFFIX=".hex",
)

env.Append(
    ASFLAGS=["-l", "-s"],
    CFLAGS=["--std-sdcc11"],
    CCFLAGS=[
        "--opt-code-size",  # optimize for size
        "--peep-return",  # peephole optimization for return instructions
        "-m%s" % board_config.get("build.cpu"),
    ],
    CPPDEFINES=["F_CPU=$BOARD_F_CPU", "HEAP_SIZE=" + __getSize("size_heap", env)],
    LINKFLAGS=[
        "-m%s" % board_config.get("build.cpu"),
        "--iram-size",
        __getSize("size_iram", env),
        "--xram-size",
        __getSize("size_xram", env),
        "--code-size",
        __getSize("size_code", env),
        "--out-fmt-ihx",
    ],
)

if int(ARGUMENTS.get("PIOVERBOSE", 0)):
    env.Prepend(UPLOADERFLAGS=["-v"])

# parse manually SDCC flags
if env.get("BUILD_FLAGS"):
    _parsed, _unparsed = _parseSdccFlags(env.get("BUILD_FLAGS"))
    env.Append(CCFLAGS=_parsed)
    env["BUILD_FLAGS"] = _unparsed

project_sdcc_flags = None
if env.get("SRC_BUILD_FLAGS"):
    project_sdcc_flags, _unparsed = _parseSdccFlags(env.get("SRC_BUILD_FLAGS"))
    env["SRC_BUILD_FLAGS"] = _unparsed

#
# Target: Build executable and linkable firmware
#

target_firm = env.BuildProgram()

if project_sdcc_flags:
    env.Import("projenv")
    projenv.Append(CCFLAGS=project_sdcc_flags)

AlwaysBuild(env.Alias("nobuild", target_firm))
target_buildprog = env.Alias("buildprog", target_firm, target_firm)

#
# Target: Print binary size
#

target_size = env.Alias(
    "size", target_firm, env.VerboseAction("$SIZEPRINTCMD", "Calculating size $SOURCE")
)
AlwaysBuild(target_size)

#
# Target: Upload firmware
#

upload_protocol = env.subst("$UPLOAD_PROTOCOL")
upload_actions = []

if upload_protocol == "stcgal":
    f_cpu_khz = int(board_config.get("build.f_cpu").strip("L")) / 1000
    stcgal_protocol = board_config.get("upload.stcgal_protocol")
    env.Replace(
        UPLOADER=join(platform.get_package_dir("tool-stcgal") or "", "stcgal.py"),
        UPLOADERFLAGS=[
            "-P",
            stcgal_protocol,
            "-p",
            "$UPLOAD_PORT",
            "-t",
            int(f_cpu_khz),
            "-a",
        ],
        UPLOADCMD='"$PYTHONEXE" "$UPLOADER" $UPLOADERFLAGS $SOURCE',
    )

    upload_actions = [
        env.VerboseAction(env.AutodetectUploadPort, "Looking for upload port..."),
        env.VerboseAction("$UPLOADCMD", "Uploading $SOURCE"),
    ]

# CH55x upload tool
elif upload_protocol == "ch55x":
    env.Replace(
        UPLOADER="vnproch55x",
        UPLOADERFLAGS=["-f"],
        UPLOADCMD="$UPLOADER $UPLOADERFLAGS $BUILD_DIR/${PROGNAME}.bin",
    )

    # Enter bootloader by opening CDC VCP at 1200bps
    port = env.subst('$UPLOAD_PORT')
    hwids = board_config.get("build.hwids")
    hwid = ':'.join(hwids[0]).replace('0x', '') if hwids else '1209:C550'
    if not port:
        from platformio import util
        ports = [sp['port'] for sp in util.get_serial_ports() if hwid == sp['hwid'].split('VID:PID=')[1][:9]]
        if ports:
            port = ports[0]
            if len(ports) > 1:
                print(f'Found multiple ports {ports} using the first one as upload port!')
    if port:
        print(f'Enter bootloader by opening {port} at 1200bps')
        try:
            __import__('serial').Serial(port, 1200).close()
        except:
            pass

    upload_actions = [
        env.VerboseAction(
            " ".join(
                [
                    "$OBJCOPY",
                    "-I",
                    "ihex",
                    "-O",
                    "binary",
                    "$SOURCE",
                    "$BUILD_DIR/${PROGNAME}.bin",
                ]
            ),
            "Creating binary",
        ),
        env.VerboseAction("$UPLOADCMD", "Uploading ${PROGNAME}.bin"),
    ]

# custom upload tool
elif upload_protocol == "custom":
    upload_actions = [env.VerboseAction("$UPLOADCMD", "Uploading $SOURCE")]

else:
    sys.stderr.write("Warning! Unknown upload protocol %s\n" % upload_protocol)

AlwaysBuild(env.Alias("upload", target_firm, upload_actions))

#
# Setup default targets
#

Default([target_buildprog, target_size])
