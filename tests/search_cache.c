/* Private search checks: include implementation without changing the public ABI. */
#include "../src/oblique.c"
#ifdef NDEBUG
#undef NDEBUG
#endif
#include <assert.h>

static OpRequest request;
static FillCache entries[FILL_CACHE_SIZE];

static Search search(void) {
    Search s={0};s.r=&request;s.deadline=op_now_ms()+10000;s.cache=entries;
    return s;
}

static void compare_fresh(Search *s,int box,const int *order,const unsigned char *used) {
    OpPlacement cached[OP_MAX_ITEMS],fresh[OP_MAX_ITEMS];double cw,fw;
    int count=fill_box(s,box,order,used,cached,&cw);
    Search reference=*s;reference.cache=NULL;reference.cache_count=0;reference.candidates=0;
    int other=fill_box(&reference,box,order,used,fresh,&fw);
    assert(count==other&&cw==fw&&!memcmp(cached,fresh,(size_t)count*sizeof *cached));
}

int main(void) {
    op_default_options(&request.options);request.options.max_candidates=100000;
    request.item_count=2;request.box_count=2;
    request.items[0]=(OpItem){"wide",2,1,1,1,0,OP_FLAT,1};
    request.items[1]=(OpItem){"tall",1,2,1,1,0,OP_FLAT,1};
    request.boxes[0]=(OpBox){"box",3,2,1,100,1,-1};
    request.boxes[1]=(OpBox){"other",4,2,1,100,1,-1};
    int order[OP_MAX_ITEMS]={0,1},reverse[OP_MAX_ITEMS]={1,0};
    unsigned char used[OP_MAX_ITEMS]={0};Search s=search();
    compare_fresh(&s,0,order,used);assert(s.cache_count==1);
    uint64_t candidates=s.candidates;
    compare_fresh(&s,0,order,used);assert(s.candidates==candidates&&s.cache_count==1);
    compare_fresh(&s,0,reverse,used);assert(s.cache_count==2&&s.candidates>candidates);
    used[0]=1;compare_fresh(&s,0,order,used);assert(s.cache_count==3);
    used[0]=0;s.run=1;compare_fresh(&s,0,order,used);assert(s.cache_count==4);
    s.run=0;s.diagonal=1;compare_fresh(&s,0,order,used);assert(s.cache_count==5);
    s.diagonal=0;compare_fresh(&s,1,order,used);assert(s.cache_count==6);

    OpPlacement current[OP_MAX_ITEMS];double weight;
    Search limited=search();request.options.max_candidates=1;
    assert(fill_box(&limited,0,order,used,current,&weight)==1);
    assert(limited.budget_exhausted&&limited.candidates==1&&limited.cache_count==0);
    request.options.max_candidates=100000;
    limited.candidates=0;limited.budget_exhausted=0;
    assert(fill_box(&limited,0,order,used,current,&weight)==2&&limited.cache_count==1);
    limited.deadline=op_now_ms()-1;
    assert(fill_box(&limited,0,order,used,current,&weight)==0&&limited.timed_out);
    limited.timed_out=0;limited.deadline=op_now_ms()+10000;
    request.options.max_candidates=limited.candidates;
    assert(fill_box(&limited,0,order,used,current,&weight)==0&&limited.budget_exhausted);

    request.options.max_candidates=100000;Search expired=search();expired.deadline=op_now_ms()-1;
    assert(fill_box(&expired,0,order,used,current,&weight)==0&&expired.cache_count==0&&expired.timed_out);
    Search bounded=search();
    for(int run=0;run<40;run++){bounded.run=run;compare_fresh(&bounded,0,order,used);}
    assert(bounded.cache_count==FILL_CACHE_SIZE);
    candidates=bounded.candidates;compare_fresh(&bounded,0,order,used);assert(bounded.candidates==candidates);
    bounded.run=0;compare_fresh(&bounded,0,order,used);assert(bounded.candidates>candidates);
    puts("search cache: exact keys, complete fills and shared budgets passed");
    return 0;
}
