// Test harness for upstream NeuralAmpModelerCore; not shipped to the pedal.
#include "NAM/get_dsp.h"
#include <fstream>
#include <vector>
int main(int argc,char **argv) {
  if(argc!=4) return 2;
  nam::DspLoadOptions options; options.prewarm=false;
  auto dsp=nam::get_dsp(std::filesystem::path(argv[1]),options);
  dsp->SetPrewarmOnReset(false); dsp->Reset(48000,8);
  std::ifstream in(argv[2],std::ios::binary);
  std::ofstream out(argv[3],std::ios::binary);
  float x[8],y[8]; float *xp=x,*yp=y;
  while(in.read(reinterpret_cast<char*>(x),sizeof(x))) {
    dsp->process(&xp,&yp,8);
    out.write(reinterpret_cast<char*>(y),sizeof(y));
  }
}
